import ast
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

import requests

from client.agent.local_server import start_local_server
from client.agent.script_parser import parse_script_config
from shared.script_contract import extract_script_archive, validate_params
from shared.version import get_version
from client.runtime.environment_manager import EnvironmentUnavailable, ensure_environment
from client.runtime.paths import ClientPaths
from client.runtime.python_runtime import PrivatePythonUnavailable, private_python, python_runtime_info

logger = logging.getLogger(__name__)

# Load client config
_CLIENT_PATHS = ClientPaths.from_environment()
_CLIENT_PATHS.ensure()
_PROJECT_ROOT = str(_CLIENT_PATHS.install_dir)
_CLIENT_CONFIG_PATH = str(_CLIENT_PATHS.config_file)
_LEGACY_CLIENT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "client_config.json")
_client_config = {}
_config_source = _CLIENT_CONFIG_PATH if os.path.isfile(_CLIENT_CONFIG_PATH) else _LEGACY_CLIENT_CONFIG_PATH
if os.path.isfile(_config_source):
    try:
        with open(_config_source, "r", encoding="utf-8") as f:
            _client_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("加载客户端配置失败: %s", e)

BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    _client_config.get("server_url", "http://127.0.0.1:8000"),
)
POLL_INTERVAL = 5
LOCAL_PORT = 18080

# Local paths for script storage and logs (decoupled from backend)
_SCRIPTS_DIR = os.environ.get(
    "SCRIPTS_DIR",
    _client_config.get("script_download_dir") or str(_CLIENT_PATHS.scripts_dir),
)
_LOGS_DIR = os.environ.get(
    "LOGS_DIR",
    str(_CLIENT_PATHS.logs_dir),
)

_token = None
_user_id = None
_current_run_id = None

# Async execution tracking (avoid blocking poll loop)
_running_proc = None      # subprocess.Popen
_running_info = {}        # {run_id, script_dir, log_path, timeout, start_time}

# Agent lifecycle state (design §4.4, §5.9)
_agent_id = None          # server-assigned agent id after register
_last_online_time = None  # last successful backend HTTP timestamp (disconnect detection)
_pending_reports = []     # cached run status updates that failed to send
_offline_notified = False  # avoid spamming disconnect notifications
_log_upload_offsets = {}  # run_id -> server-acknowledged UTF-8 byte offset
_pending_log_uploads = {}  # run_id -> local log path requiring a final retry
_last_update_check_time = 0
_restart_requested = False
_last_settings_sync_time = 0

_CLIENT_SETTING_KEYS = {
    "server_url",
    "script_download_dir",
    "output_dir",
    "default_browser_path",
    "browser_debug_port",
    "proxy",
    "pip_index_url",
    "github_update_repository",
    "update_channel",
    "update_manifest_urls",
}

OFFLINE_NOTIFY_THRESHOLD_SEC = 30 * 60  # 30 min (design §5.9)
UPDATE_CHECK_INTERVAL_SEC = 6 * 60 * 60
PENDING_REPORTS_FILE = str(_CLIENT_PATHS.runs_dir / "pending_reports.json")
PENDING_LOG_UPLOADS_FILE = str(_CLIENT_PATHS.runs_dir / "pending_log_uploads.json")


def _parse_result_literal(raw):
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return raw


def _install_downloaded_script(payload, script_dir):
    """Validate, normalize, and atomically install a downloaded script ZIP."""
    target = Path(script_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(target.parent)))
    try:
        archive = work / "script.zip"
        archive.write_bytes(payload)
        extracted = work / "content"
        main_path = extract_script_archive(archive, extracted)
        source = extracted
        if main_path.parent != extracted:
            source = work / "normalized"
            shutil.copytree(main_path.parent, source)
        if target.exists():
            raise FileExistsError(f"脚本目录已存在: {target}")
        os.replace(source, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _get_venv_pip():
    """Return the pip path for the project venv."""
    venv_root = os.path.join(os.path.dirname(__file__), "..", "..", ".venv")
    if sys.platform == "win32":
        return os.path.join(venv_root, "Scripts", "pip.exe")
    return os.path.join(venv_root, "bin", "pip")


def _get_installed_packages(python_executable=None):
    """Return a set of installed package names (lowercase)."""
    python_bin = python_executable or sys.executable
    try:
        result = subprocess.run(
            [python_bin, "-m", "pip", "list", "--format=json"],
            capture_output=True, timeout=30, text=True,
        )
        if result.returncode == 0:
            pkgs = json.loads(result.stdout)
            return {p["name"].lower() for p in pkgs}
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("pip list 失败: %s", e)
    return set()


def ensure_dependencies(script_config, python_executable=None):
    """Check config requirements, install missing packages. Returns error string or None."""
    requirements = script_config.get("requirements", [])
    if not requirements:
        return None

    installed = _get_installed_packages(python_executable)

    # Parse requirement strings: "package>=1.0" → "package"
    missing = []
    for req in requirements:
        pkg_name = req.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip().lower()
        if pkg_name not in installed:
            missing.append(req)

    if not missing:
        return None

    python_bin = python_executable or sys.executable
    print("正在安装缺失依赖: {}".format(", ".join(missing)))
    try:
        result = subprocess.run(
            [python_bin, "-m", "pip", "install"] + missing,
            capture_output=True, timeout=300, text=True,
        )
        if result.returncode != 0:
            return "Dependency install failed: {}".format(result.stderr[:500])
        print("依赖安装成功")
        return None
    except subprocess.TimeoutExpired:
        return "Dependency install timed out"
    except Exception as e:
        return "Dependency install error: {}".format(str(e))


def prepare_script_environment(script_config, offline=False):
    """Return the fingerprinted venv interpreter or an actionable error."""
    try:
        runtime = private_python(_CLIENT_PATHS)
    except PrivatePythonUnavailable:
        if getattr(sys, "frozen", False):
            return None, "私有 Python 3.11.9 缺失，请修复或重新安装客户端"
        runtime = Path(sys.executable)
    try:
        result = ensure_environment(
            script_config.get("requirements", []),
            _CLIENT_PATHS,
            index_url=_client_config.get("pip_index_url") or None,
            offline=offline,
            python_executable=runtime,
        )
        return str(result.python_executable), None
    except (EnvironmentUnavailable, RuntimeError, OSError, ValueError) as exc:
        return None, "脚本环境准备失败: {}".format(exc)


def _validate_run_params(param_defs, params):
    """Pre-execution parameter validation (design §5.2).

    Runs on the Agent (not the backend) because file/folder targets live on the
    client machine. Validates: required non-empty, file existence, folder existence
    (auto-creates if auto_create=True), number range, select options.
    Returns list of error strings.
    """
    preflight_errors = []
    for definition in param_defs:
        if definition.get("type") != "folder" or not definition.get("auto_create"):
            continue
        value = params.get(definition.get("key"))
        if value and not os.path.isdir(value):
            try:
                os.makedirs(value, exist_ok=True)
                print("已自动创建目录: {}".format(value))
            except OSError as exc:
                preflight_errors.append(
                    "{}: 目录自动创建失败 - {}".format(definition.get("label", value), exc)
                )
    return preflight_errors + validate_params(param_defs, params, check_paths=True)


def authenticate(username, password):
    global _token, _user_id
    try:
        resp = requests.post(
            "{}/api/auth/login".format(BACKEND_URL),
            json={"username": username, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _token = data["token"]
            _user_id = data["user"]["id"]
            return True
    except (requests.RequestException, OSError):
        pass
    return False


def _headers():
    return {"Authorization": "Bearer {}".format(_token)}


def _upload_log_delta(run_id, log_path, force=False):
    """Upload only the UTF-8 log bytes not yet acknowledged by the backend."""
    if not run_id or not log_path or not os.path.isfile(log_path):
        return True

    offset = int(_log_upload_offsets.get(run_id, 0) or 0)
    try:
        size = os.path.getsize(log_path)
        if offset > size:
            offset = 0
        with open(log_path, "rb") as f:
            f.seek(offset)
            raw = f.read()
    except OSError:
        return False

    if not raw:
        return True

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if not force and e.reason == "unexpected end of data" and e.start > 0:
            raw = raw[:e.start]
            content = raw.decode("utf-8")
        else:
            content = raw.decode("utf-8", errors="replace")
    if not raw:
        return True

    try:
        resp = requests.post(
            "{}/api/runs/{}/log/chunk".format(BACKEND_URL, run_id),
            json={"offset": offset, "content": content},
            headers=_headers(),
            timeout=10,
        )
        data = resp.json()
        if resp.status_code == 200:
            _log_upload_offsets[run_id] = int(data["offset"])
            return True
        if resp.status_code == 409:
            detail = data.get("detail") or {}
            if "offset" in detail:
                _log_upload_offsets[run_id] = int(detail["offset"])
    except (requests.RequestException, OSError, KeyError, TypeError, ValueError):
        pass
    return False


def _finish_log_upload(run_id, log_path):
    """Force the final delta and persist a retry when the backend is unavailable."""
    if _upload_log_delta(run_id, log_path, force=True):
        _pending_log_uploads.pop(run_id, None)
        _save_pending_log_uploads()
        return True
    _pending_log_uploads[run_id] = log_path
    _save_pending_log_uploads()
    return False


def _flush_pending_log_uploads():
    for run_id, path in list(_pending_log_uploads.items()):
        if _upload_log_delta(run_id, path, force=True):
            _pending_log_uploads.pop(run_id, None)
    _save_pending_log_uploads()


def _normalize_result_files(value, base_dir=None):
    """Convert script result paths into metadata without uploading file content."""
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    metadata = []
    for item in values:
        path = item.get("path") if isinstance(item, dict) else item
        if not isinstance(path, str) or not path:
            continue
        resolved = path
        if base_dir and not os.path.isabs(resolved):
            resolved = os.path.join(base_dir, resolved)
        absolute = os.path.abspath(resolved)
        exists = os.path.isfile(absolute)
        try:
            size = os.path.getsize(absolute) if exists else None
        except OSError:
            size = None
        metadata.append({
            "name": os.path.basename(absolute),
            "path": absolute,
            "exists": exists,
            "size": size,
        })
    return metadata


def open_local_result(path):
    """Open a result file on the Agent machine that actually executed the script."""
    if not isinstance(path, str) or not path:
        return {"success": False, "error": "未提供结果文件路径"}
    absolute = os.path.abspath(path)
    if not os.path.isfile(absolute):
        return {"success": False, "error": "结果文件不存在: {}".format(absolute)}
    try:
        os.startfile(absolute)
        return {"success": True, "path": absolute}
    except OSError as e:
        return {"success": False, "error": "打开结果文件失败: {}".format(e)}


def _sync_client_settings():
    """Pull per-user settings and persist allowed fields on this Agent machine."""
    global _client_config
    try:
        resp = requests.get(
            "{}/api/settings".format(BACKEND_URL),
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return False
        remote = resp.json() or {}

        local = dict(_client_config)
        if os.path.isfile(_CLIENT_CONFIG_PATH):
            try:
                with open(_CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
                    local = json.load(f) or local
            except (OSError, json.JSONDecodeError):
                pass

        for key in _CLIENT_SETTING_KEYS:
            if key in remote and remote[key] is not None:
                local[key] = remote[key]

        temp_path = _CLIENT_CONFIG_PATH + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(local, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, _CLIENT_CONFIG_PATH)
        _client_config = local
        return True
    except (requests.RequestException, OSError, TypeError, ValueError):
        return False


def _get_current_run_id():
    return _current_run_id


def _start_script_subprocess(script_dir, params, log_path, timeout, env_vars=None, python_executable=None):
    """Start a script subprocess asynchronously (non-blocking). Returns Popen."""
    # Resolve absolute paths — the child subprocess runs with cwd=script_dir, so any
    # relative path passed in would be interpreted relative to a different cwd than the
    # parent Agent process. Abspath ensures parent and child see the same files.
    script_dir = os.path.abspath(script_dir)
    log_path = os.path.abspath(log_path)

    # Write params to temp file (next to the log file)
    params_file = os.path.join(os.path.dirname(log_path), "_params.json")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(params_file, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False)

    code = (
        "import sys, json, os; "
        "sys.path.insert(0, sys.argv[1]); "
        "_pf = os.path.join(os.path.dirname(sys.argv[2]), '_params.json'); "
        "_params = json.load(open(_pf, encoding='utf-8')); "
        "from main import main; "
        "result = main(**_params); "
        "sys.stdout.buffer.write(('__RESULT__:' + repr(result)).encode('utf-8'))"
    )

    proc_env = os.environ.copy()
    # Force child process to encode stdout/stderr as UTF-8 — Windows defaults to cp936 (GBK)
    # which produces mojibake when the backend reads the log as UTF-8.
    proc_env["PYTHONIOENCODING"] = "utf-8"
    if env_vars:
        proc_env.update(env_vars)

    python_bin = python_executable or sys.executable
    # Open log in BINARY mode — the child writes bytes (UTF-8 thanks to PYTHONIOENCODING);
    # text mode here would double-encode and corrupt non-ASCII output (Chinese paths, etc.)
    log_file = open(log_path, "wb")

    proc = subprocess.Popen(
        [python_bin, "-c", code, script_dir, log_path],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=script_dir,
        env=proc_env,
    )
    # Store log_file so it can be closed later
    proc._log_file = log_file
    proc._params_file = params_file
    return proc


def _check_running_process():
    """Check if the running process has finished. Returns result dict or None if still running."""
    global _running_proc, _running_info, _current_run_id

    if _running_proc is None:
        return None

    ret = _running_proc.poll()
    if ret is None:
        # Still running — check timeout
        elapsed = time.time() - _running_info["start_time"]
        if elapsed > _running_info["timeout"]:
            _running_proc.kill()
            _running_proc._log_file.close()
            try:
                os.remove(_running_proc._params_file)
            except OSError:
                pass
            _running_proc = None
            _current_run_id = None
            info = dict(_running_info)
            _running_info = {}
            return {
                "status": "failed",
                "error": "Timeout after {}s".format(info["timeout"]),
                "result": None,
                "run_id": info.get("run_id"),
                "log_path": info.get("log_path"),
            }
        return None  # still running

    # Process finished
    _running_proc._log_file.close()
    try:
        os.remove(_running_proc._params_file)
    except OSError:
        pass

    log_path = _running_info["log_path"]
    run_id = _running_info["run_id"]

    # Read log to find result
    result_value = None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("__RESULT__:"):
                    raw = line[len("__RESULT__:"):].strip()
                    try:
                        result_value = _parse_result_literal(raw)
                    except Exception:
                        result_value = raw
                    break
    except OSError:
        pass

    status = "success" if ret == 0 else "failed"
    error = None if ret == 0 else "Exit code: {}".format(ret)

    _running_proc = None
    _current_run_id = None
    info = dict(_running_info)
    _running_info = {}

    return {
        "status": status,
        "error": error,
        "result": result_value,
        "run_id": run_id,
        "log_path": log_path,
        "script_dir": info.get("script_dir"),
    }


def _detect_machine_info():
    """Detect local machine name and primary IP."""
    import socket
    try:
        machine_name = socket.gethostname() or "unknown"
    except OSError:
        machine_name = "unknown"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        machine_ip = s.getsockname()[0]
        s.close()
    except OSError:
        machine_ip = "127.0.0.1"
    return machine_name, machine_ip


def register_agent():
    """Register this agent with backend (design §4.4). Returns agent_id or None."""
    global _agent_id, _last_online_time
    machine_name, machine_ip = _detect_machine_info()
    agent_version = get_version()
    try:
        resp = requests.post(
            "{}/api/agents/register".format(BACKEND_URL),
            json={"machine_name": machine_name, "machine_ip": machine_ip, "agent_version": agent_version},
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            _agent_id = resp.json()["id"]
            _last_online_time = time.time()
            print("Agent 已注册: id={} 机器={}".format(_agent_id, machine_name))
            return _agent_id
    except (requests.RequestException, OSError) as e:
        print("Agent 注册失败: {}".format(e))
    return None


def send_heartbeat():
    """Send heartbeat to backend; updates _last_online_time on success (design §5.1)."""
    global _last_online_time, _offline_notified, _token
    if not _agent_id:
        return False
    _, machine_ip = _detect_machine_info()
    try:
        resp = requests.post(
            "{}/api/agents/{}/heartbeat".format(BACKEND_URL, _agent_id),
            json={"machine_ip": machine_ip},
            headers=_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            _last_online_time = time.time()
            _offline_notified = False
            return True
        if resp.status_code == 401:
            _token = None
    except (requests.RequestException, OSError):
        pass
    return False


def _check_offline_notification():
    """Pop system notification if disconnected > 30 min (design §5.9)."""
    global _offline_notified
    if not _last_online_time or _offline_notified:
        return
    offline_secs = time.time() - _last_online_time
    if offline_secs > OFFLINE_NOTIFY_THRESHOLD_SEC:
        try:
            from client.agent.notifier import show_system_notification
            show_system_notification(
                "AutoScript Hub 断线",
                "已与服务端断开连接 {} 分钟,请检查网络或联系管理员".format(int(offline_secs // 60)),
            )
            _offline_notified = True
        except Exception as e:
            logger.warning("显示离线通知失败: %s", e)


def _save_pending_reports():
    """Persist cached reports to disk so they survive process restart."""
    try:
        parent = os.path.dirname(PENDING_REPORTS_FILE)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(PENDING_REPORTS_FILE, "w", encoding="utf-8") as f:
            json.dump(_pending_reports, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("保存待上报记录失败: %s", e)


def _save_pending_log_uploads():
    try:
        if not _pending_log_uploads:
            if os.path.isfile(PENDING_LOG_UPLOADS_FILE):
                os.remove(PENDING_LOG_UPLOADS_FILE)
            return
        parent = os.path.dirname(PENDING_LOG_UPLOADS_FILE)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(PENDING_LOG_UPLOADS_FILE, "w", encoding="utf-8") as f:
            json.dump(_pending_log_uploads, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("保存待上传日志失败: %s", e)


def _load_pending_log_uploads():
    global _pending_log_uploads
    try:
        if os.path.isfile(PENDING_LOG_UPLOADS_FILE):
            with open(PENDING_LOG_UPLOADS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f) or {}
            _pending_log_uploads = {int(run_id): path for run_id, path in saved.items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("加载待上传日志失败: %s", e)
        _pending_log_uploads = {}


def _load_pending_reports():
    """Load cached reports from disk on startup."""
    global _pending_reports
    try:
        if os.path.isfile(PENDING_REPORTS_FILE):
            with open(PENDING_REPORTS_FILE, "r", encoding="utf-8") as f:
                _pending_reports = json.load(f) or []
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("加载待上报记录失败: %s", e)
        _pending_reports = []


def _flush_pending_reports():
    """Retry sending cached reports. Removes entries that succeed (design §5.9)."""
    global _pending_reports
    if not _pending_reports:
        return
    remaining = []
    for item in _pending_reports:
        run_id = item.get("run_id")
        update = item.get("update", {})
        try:
            resp = requests.patch(
                "{}/api/runs/{}/status".format(BACKEND_URL, run_id),
                json=update, headers=_headers(), timeout=10,
            )
            if resp.status_code != 200:
                remaining.append(item)
        except (requests.RequestException, OSError):
            remaining.append(item)
    _pending_reports = remaining
    _save_pending_reports()


def _report_run_status(run_id, update):
    """Report run status to backend. Cache locally on failure for later retry (design §5.9)."""
    global _last_online_time
    try:
        resp = requests.patch(
            "{}/api/runs/{}/status".format(BACKEND_URL, run_id),
            json=update, headers=_headers(), timeout=10,
        )
        if resp.status_code == 200:
            _last_online_time = time.time()
            return True
    except (requests.RequestException, OSError):
        pass
    # Cache for next-cycle retry
    _pending_reports.append({"run_id": run_id, "update": update, "cached_at": time.time()})
    _save_pending_reports()
    return False


# === Local (offline) run management (design §5.x offline mode) ===
# Local runs execute scripts already cached on this machine without consulting the
# backend. Finished local runs are synced to the backend when connectivity returns,
# producing backend run records with the offline result back-filled.
_local_runs = {}              # local_run_id (e.g. "L1") → record dict
_local_run_counter = 0
_local_runs_file = str(_CLIENT_PATHS.runs_dir / "local_runs.json")
# Subprocess for the *currently running* local run (one at a time)
_local_run_proc = None
_local_run_info = {}


def _save_local_runs():
    """Persist local runs to disk so they survive process restart."""
    try:
        parent = os.path.dirname(_local_runs_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(_local_runs_file, "w", encoding="utf-8") as f:
            json.dump(_local_runs, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("保存本地执行记录失败: %s", e)


def _load_local_runs():
    """Load local runs from disk on startup. Recovers the run-id counter."""
    global _local_runs, _local_run_counter
    try:
        if os.path.isfile(_local_runs_file):
            with open(_local_runs_file, "r", encoding="utf-8") as f:
                _local_runs = json.load(f) or {}
            for k in _local_runs.keys():
                try:
                    n = int(k.lstrip("L"))
                    if n > _local_run_counter:
                        _local_run_counter = n
                except ValueError:
                    pass
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("加载本地执行记录失败: %s", e)
        _local_runs = {}


def list_local_scripts():
    """Scan local script cache; return [{id, latest_version, name, ...}].

    Each script_id subdirectory under _SCRIPTS_DIR contains version subdirs.
    For each, we parse main.py's config() to surface metadata to the offline UI.
    """
    result = []
    if not os.path.isdir(_SCRIPTS_DIR):
        return result
    for script_id_str in os.listdir(_SCRIPTS_DIR):
        script_dir = os.path.join(_SCRIPTS_DIR, script_id_str)
        if not os.path.isdir(script_dir):
            continue
        try:
            script_id = int(script_id_str)
        except ValueError:
            continue
        versions = []
        for v in os.listdir(script_dir):
            try:
                versions.append(int(v))
            except ValueError:
                continue
        if not versions:
            continue
        latest_ver = max(versions)
        main_path = os.path.join(script_dir, str(latest_ver), "main.py")
        try:
            config = parse_script_config(main_path) or {}
        except Exception as e:
            logger.warning("解析本地脚本 %s v%s 失败: %s", script_id, latest_ver, e)
            config = {}
        result.append({
            "id": script_id,
            "latest_version": latest_ver,
            "name": config.get("name", "Script #{}".format(script_id)),
            "description": config.get("description", ""),
            "category": config.get("category", ""),
            "config": config,
            "config_json": json.dumps(config, ensure_ascii=False),
            "local_only": True,
        })
    return result


def start_local_run(req):
    """Start a script locally without going through the backend.

    req: {script_id, params, env_vars?}
    Returns the local run record. Mutates state to track the subprocess.
    """
    global _local_run_counter, _local_run_proc, _local_run_info
    # Same one-at-a-time rule as backend-triggered runs
    if _local_run_proc is not None or _running_proc is not None:
        return {"error": "another task is running"}

    script_id = req.get("script_id")
    params = req.get("params") or {}
    if not script_id:
        return {"error": "script_id required"}

    script_dir = os.path.join(_SCRIPTS_DIR, str(script_id))
    if not os.path.isdir(script_dir):
        return {"error": "script not downloaded locally"}

    versions = []
    for v in os.listdir(script_dir):
        try:
            versions.append(int(v))
        except ValueError:
            continue
    if not versions:
        return {"error": "no script versions cached locally"}
    latest_ver = max(versions)
    run_script_dir = os.path.join(script_dir, str(latest_ver))

    config_path = os.path.join(run_script_dir, "main.py")
    script_config = {}
    try:
        script_config = parse_script_config(config_path) or {}
    except Exception as e:
        logger.warning("解析脚本配置失败: %s", e)

    script_python = None
    if script_config:
        script_python, dep_error = prepare_script_environment(
            script_config,
            offline=not get_connection_status().get("online", False),
        )
        if dep_error:
            return {"error": dep_error}

    timeout = script_config.get("timeout", 600)

    _local_run_counter += 1
    local_run_id = "L{}".format(_local_run_counter)

    os.makedirs(_LOGS_DIR, exist_ok=True)
    log_path = os.path.join(_LOGS_DIR, "local_{}.log".format(local_run_id))

    # UI can pass environment vars directly (offline: no Environment table access)
    env_vars = req.get("env_vars") or None

    proc = _start_script_subprocess(
        run_script_dir, params, log_path, timeout,
        env_vars=env_vars, python_executable=script_python,
    )
    _local_run_proc = proc
    _local_run_info = {
        "local_run_id": local_run_id,
        "script_id": script_id,
        "script_version": latest_ver,
        "script_name": script_config.get("name"),
        "script_dir": run_script_dir,
        "log_path": log_path,
        "timeout": timeout,
        "start_time": time.time(),
        "params": params,
    }

    record = {
        "local_run_id": local_run_id,
        "script_id": script_id,
        "script_version": latest_ver,
        "script_name": script_config.get("name"),
        "params": params,
        "status": "running",
        "started_at": _local_run_info["start_time"],
        "finished_at": None,
        "duration_sec": None,
        "error_msg": None,
        "result_files": None,
        "log_path": log_path,
        "synced": False,
        "backend_run_id": None,
    }
    _local_runs[local_run_id] = record
    _save_local_runs()

    print("本地执行已启动: {} (脚本 {} v{})".format(local_run_id, script_id, latest_ver))
    return record


def _check_local_runs():
    """Advance the currently running local run's state if its subprocess exited."""
    global _local_run_proc, _local_run_info
    if _local_run_proc is None:
        return None

    ret = _local_run_proc.poll()
    if ret is None:
        elapsed = time.time() - _local_run_info["start_time"]
        if elapsed > _local_run_info["timeout"]:
            _local_run_proc.kill()
            try:
                _local_run_proc._log_file.close()
                os.remove(_local_run_proc._params_file)
            except (OSError, AttributeError):
                pass
            info = dict(_local_run_info)
            _local_run_proc = None
            _local_run_info = {}
            _record_local_run_completion(info, status="failed", error="Timeout after {}s".format(info["timeout"]), result=None)
            return info["local_run_id"]
        return None

    # Subprocess exited
    try:
        _local_run_proc._log_file.close()
        os.remove(_local_run_proc._params_file)
    except (OSError, AttributeError):
        pass

    info = dict(_local_run_info)
    log_path = info["log_path"]

    result_value = None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("__RESULT__:"):
                    raw = line[len("__RESULT__:"):].strip()
                    try:
                        result_value = _parse_result_literal(raw)
                    except Exception:
                        result_value = raw
                    break
    except OSError:
        pass

    status = "success" if ret == 0 else "failed"
    error = None if ret == 0 else "Exit code: {}".format(ret)

    _local_run_proc = None
    _local_run_info = {}
    _record_local_run_completion(info, status=status, error=error, result=result_value)
    return info["local_run_id"]


def _record_local_run_completion(info, status, error, result):
    """Update a local run record after its subprocess exits; pop a notification."""
    local_run_id = info["local_run_id"]
    if local_run_id not in _local_runs:
        return
    finished = time.time()
    rec = _local_runs[local_run_id]
    rec["status"] = status
    rec["error_msg"] = error
    rec["finished_at"] = finished
    rec["duration_sec"] = int(finished - rec["started_at"]) if rec.get("started_at") else None
    if result is not None:
        rec["result_files"] = json.dumps(
            _normalize_result_files(result, base_dir=info.get("script_dir")),
            ensure_ascii=False,
        )
    _save_local_runs()

    # System bubble notification (design §5.5)
    try:
        from client.agent.notifier import show_system_notification
        title = "AutoScript Hub"
        name = rec.get("script_name") or "脚本"
        if status == "success":
            show_system_notification(title, "{} 执行完成".format(name))
        else:
            show_system_notification(title, "{} 执行失败:{}".format(name, error or "未知错误"))
    except Exception as e:
        logger.warning("通知失败: %s", e)


def list_local_runs():
    """Return all local run records, newest first."""
    items = list(_local_runs.values())
    items.sort(key=lambda r: r.get("started_at", 0) or 0, reverse=True)
    return items


def get_local_run(local_run_id):
    return _local_runs.get(local_run_id)


def get_local_run_log(local_run_id):
    rec = _local_runs.get(local_run_id)
    if not rec:
        return {"log": "", "error": "not found"}
    log_path = rec.get("log_path") or ""
    if not log_path or not os.path.isfile(log_path):
        return {"log": ""}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return {"log": f.read()}
    except OSError as e:
        return {"log": "", "error": str(e)}


def get_connection_status():
    """Client's view of backend connectivity, for the offline UI banner."""
    online = _last_online_time is not None and (time.time() - _last_online_time) < 90
    pending_sync = sum(
        1 for r in _local_runs.values()
        if not r.get("synced") and r.get("status") in ("success", "failed")
    )
    return {
        "online": online,
        "last_online_at": _last_online_time,
        "pending_sync_count": pending_sync,
        "agent_id": _agent_id,
    }


def _sync_local_runs_to_backend():
    """Push finished, unsynced local runs to backend when connectivity is back.

    For each local run:
      1. POST /api/runs/execute → creates a backend run record
      2. PATCH /api/runs/{id}/status → back-fills final status + result
      3. Mark local run as synced (with backend_run_id)
    """
    if not _agent_id or not _last_online_time:
        return
    if time.time() - _last_online_time > 90:
        return  # not online

    for local_run_id, rec in list(_local_runs.items()):
        if rec.get("synced"):
            continue
        if rec.get("status") not in ("success", "failed"):
            continue
        try:
            create_resp = requests.post(
                "{}/api/runs/execute".format(BACKEND_URL),
                json={
                    "script_id": rec["script_id"],
                    "params": rec.get("params") or {},
                },
                headers=_headers(),
                timeout=10,
            )
            if create_resp.status_code != 200:
                continue
            backend_run_id = create_resp.json()["id"]

            if rec.get("log_path") and not _upload_log_delta(
                backend_run_id, rec["log_path"], force=True
            ):
                continue

            update = {"status": rec["status"]}
            if _agent_id:
                update["agent_id"] = _agent_id
            if rec.get("error_msg"):
                update["error_msg"] = rec["error_msg"]
            if rec.get("result_files"):
                update["result_files"] = rec["result_files"]

            patch_resp = requests.patch(
                "{}/api/runs/{}/status".format(BACKEND_URL, backend_run_id),
                json=update,
                headers=_headers(),
                timeout=10,
            )
            if patch_resp.status_code == 200:
                rec["synced"] = True
                rec["backend_run_id"] = backend_run_id
                _save_local_runs()
                print("本地执行 {} 已同步为后端记录 {}".format(local_run_id, backend_run_id))
        except (requests.RequestException, OSError, KeyError, ValueError) as e:
            logger.debug("同步 {} 失败: {}".format(local_run_id, e))


def poll_and_execute():
    """Non-blocking poll: check running process or start new run."""
    global _running_proc, _running_info, _current_run_id

    # Upload live log bytes before other polling work.
    if _running_proc is not None and _running_info.get("run_id") and _running_info.get("log_path"):
        _upload_log_delta(_running_info["run_id"], _running_info["log_path"])

    # 0) Cancel propagation (design §5.1): cancel only flips backend status — the Agent
    #    must independently notice and kill its subprocess, otherwise the cancelled run
    #    blocks every subsequent run indefinitely (_running_proc never clears).
    if _running_proc is not None and _running_info.get("run_id"):
        try:
            check_resp = requests.get(
                "{}/api/runs/{}".format(BACKEND_URL, _running_info["run_id"]),
                headers=_headers(), timeout=5,
            )
            if check_resp.status_code == 200 and check_resp.json().get("status") == "cancelled":
                print("后端已取消任务 {},终止子进程".format(_running_info["run_id"]))
                try:
                    _running_proc.kill()
                    _running_proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                try:
                    _running_proc._log_file.close()
                    os.remove(_running_proc._params_file)
                except (OSError, AttributeError):
                    pass
                _running_proc = None
                _current_run_id = None
                _running_info = {}
                return  # next cycle picks up new pending runs
        except (requests.RequestException, OSError):
            pass  # best-effort: if check fails, normal timeout watchdog still applies

    # 1) Check running process
    result = _check_running_process()
    if result:
        run_id = result.pop("run_id", None)
        actual_log_path = result.pop("log_path", None)
        result_script_dir = result.pop("script_dir", None)
        if run_id:
            if actual_log_path:
                _finish_log_upload(run_id, actual_log_path)
            update = {"status": result["status"]}
            if result.get("error"):
                update["error_msg"] = result["error"]
            if result.get("result"):
                update["result_files"] = json.dumps(
                    _normalize_result_files(result["result"], base_dir=result_script_dir),
                    ensure_ascii=False,
                )
            _report_run_status(run_id, update)
        return  # Don't start new run yet (next poll cycle)

    # 2) If already running, don't start another
    if _running_proc is not None:
        return

    # 3) Look for pending run
    try:
        resp = requests.get(
            "{}/api/runs?status=pending&limit=1".format(BACKEND_URL),
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code != 200 or not resp.json():
            return

        run = resp.json()[0]
        run_id = run["id"]
        _current_run_id = run_id
        script_id = run["script_id"]

        # Get script info
        script_resp = requests.get(
            "{}/api/scripts/{}".format(BACKEND_URL, script_id),
            headers=_headers(),
            timeout=10,
        )
        if script_resp.status_code != 200:
            _current_run_id = None
            return

        script = script_resp.json()
        ver = script["latest_version"]
        script_dir = os.path.join(_SCRIPTS_DIR, str(script_id), str(ver))
        os.makedirs(_LOGS_DIR, exist_ok=True)

        # Download script files if not present locally
        if not os.path.isdir(script_dir):
            print("正在下载脚本 {} v{}...".format(script_id, ver))
            dl_resp = requests.get(
                "{}/api/scripts/{}/download?version={}".format(BACKEND_URL, script_id, ver),
                headers=_headers(), timeout=30, stream=True,
            )
            if dl_resp.status_code == 200:
                _install_downloaded_script(dl_resp.content, script_dir)
                print("脚本已下载到 {}".format(script_dir))
            else:
                _report_run_status(run_id, {"status": "failed", "error_msg": "Failed to download script files"})
                _current_run_id = None
                return

        log_path = os.path.join(_LOGS_DIR, "{}.log".format(run_id))

        # Apply environment config
        env_vars = {}
        python_executable = None
        env_id = run.get("environment_id")
        if env_id:
            try:
                env_resp = requests.get(
                    "{}/api/environments/{}".format(BACKEND_URL, env_id),
                    headers=_headers(), timeout=10,
                )
                if env_resp.status_code == 200:
                    env_cfg = env_resp.json()
                    if env_cfg.get("browser_port"):
                        env_vars["BROWSER_PORT"] = str(env_cfg["browser_port"])
                    if env_cfg.get("browser_path"):
                        env_vars["BROWSER_PATH"] = env_cfg["browser_path"]
                    if env_cfg.get("output_dir"):
                        env_vars["OUTPUT_DIR"] = env_cfg["output_dir"]
                    if env_cfg.get("proxy"):
                        env_vars["http_proxy"] = env_cfg["proxy"]
                        env_vars["https_proxy"] = env_cfg["proxy"]
                    if env_cfg.get("extra_env"):
                        for k, v in env_cfg["extra_env"].items():
                            env_vars[k] = str(v)
                    if env_cfg.get("python_executable"):
                        python_executable = env_cfg["python_executable"]
                    print("使用环境: {} ({} 个变量, python={})".format(
                        env_cfg.get("name"), len(env_vars),
                        python_executable or "default"))
            except Exception as e:
                print("加载环境配置失败: {}".format(e))

        # Check and install dependencies
        script_config = {}
        config_path = os.path.join(script_dir, "main.py")
        try:
            script_config = parse_script_config(config_path) or {}
        except Exception as e:
            logger.warning("解析脚本配置失败: %s", e)

        if script_config:
            script_python, dep_error = prepare_script_environment(script_config, offline=False)
            if dep_error:
                _report_run_status(run_id, {"status": "failed", "error_msg": dep_error})
                _current_run_id = None
                return
            python_executable = script_python

            # Pre-execution parameter validation (design §5.2): file/folder existence etc.
            param_defs = script_config.get("params", [])
            if param_defs:
                params_for_check = json.loads(run["params"]) if run.get("params") else {}
                val_errors = _validate_run_params(param_defs, params_for_check)
                if val_errors:
                    _report_run_status(run_id, {
                        "status": "failed",
                        "error_msg": "参数校验失败: " + "; ".join(val_errors),
                    })
                    _current_run_id = None
                    return

        timeout = script_config.get("timeout", 600)

        # Mark as running
        running_update = {"status": "running"}
        if _agent_id:
            running_update["agent_id"] = _agent_id
        _report_run_status(run_id, running_update)

        # Start subprocess asynchronously
        params = json.loads(run["params"]) if run.get("params") else {}
        proc = _start_script_subprocess(
            script_dir, params, log_path, timeout,
            env_vars=env_vars or None, python_executable=python_executable,
        )

        _running_proc = proc
        _running_info = {
            "run_id": run_id,
            "script_dir": script_dir,
            "log_path": log_path,
            "timeout": timeout,
            "start_time": time.time(),
        }
        print("脚本执行已启动 (PID {}, 任务 {})".format(proc.pid, run_id))

    except Exception as e:
        if _current_run_id:
            _report_run_status(_current_run_id, {"status": "failed", "error_msg": str(e)})
        _current_run_id = None


def _compare_versions(local_ver, remote_ver):
    """Compare two version strings like '1.2.3'. Returns True if remote is newer."""
    def _parts(v):
        return [int(x) for x in v.split(".")]
    try:
        l, r = _parts(local_ver), _parts(remote_ver)
    except (ValueError, AttributeError):
        return False
    return r > l


def _check_and_stage_update():
    """Check public signed sources and stage a verified installer without applying it."""
    from client.agent.updater import check_and_stage_update
    local_version = get_version()
    return check_and_stage_update(
        current_version=local_version,
        runtime_is_idle=lambda: _running_proc is None and _local_run_proc is None,
    )


def _get_update_status():
    from client.agent.updater import get_update_status
    return get_update_status()


def _get_runtime_info():
    try:
        info = python_runtime_info(_CLIENT_PATHS)
        return {
            "status": "ready" if info["ready"] else "invalid",
            "managed": True,
            "version": info["actual_version"],
            "expected_version": info["expected_version"],
            "path": info["path"],
        }
    except (PrivatePythonUnavailable, OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "unavailable",
            "managed": True,
            "expected_version": "3.11.9",
            "error": str(exc),
        }


def _install_staged_update():
    global _restart_requested
    from client.agent.updater import install_staged_update
    local_version = get_version()
    result = install_staged_update(
        current_version=local_version,
        runtime_is_idle=lambda: _running_proc is None and _local_run_proc is None,
    )
    if result.get("state") == "installing":
        _restart_requested = True
    return result


def initialize_agent_runtime():
    """Load cached state and start the local API before any backend connection."""
    _load_pending_reports()
    _load_pending_log_uploads()
    _load_local_runs()
    server_thread = start_local_server(
        LOCAL_PORT,
        _get_current_run_id,
        get_version_fn=get_version,
        list_local_scripts_fn=list_local_scripts,
        start_local_run_fn=start_local_run,
        list_local_runs_fn=list_local_runs,
        get_local_run_fn=get_local_run,
        get_local_run_log_fn=get_local_run_log,
        get_connection_status_fn=get_connection_status,
        open_result_fn=open_local_result,
        get_update_status_fn=_get_update_status,
        check_update_fn=_check_and_stage_update,
        install_update_fn=_install_staged_update,
        get_runtime_info_fn=_get_runtime_info,
    )
    server_thread.daemon = True
    server_thread.start()
    return server_thread


def agent_iteration(username, password):
    """Run one online/offline Agent loop iteration without exiting on disconnect."""
    global _last_update_check_time, _restart_requested, _last_settings_sync_time

    if not _token:
        if not authenticate(username, password):
            _check_local_runs()
            _check_offline_notification()
            return False
        print("Agent 已认证为 {},每 {} 秒轮询一次".format(username, POLL_INTERVAL))
        register_agent()

    now = time.time()
    if _last_update_check_time == 0 or now - _last_update_check_time >= UPDATE_CHECK_INTERVAL_SEC:
        _last_update_check_time = now
        _check_and_stage_update()
    if now - _last_settings_sync_time >= 60:
        if _sync_client_settings():
            _last_settings_sync_time = now

    _flush_pending_reports()
    _flush_pending_log_uploads()
    _check_local_runs()
    if (
        _get_update_status().get("state") == "waiting-for-idle"
        and _running_proc is None
        and _local_run_proc is None
    ):
        result = _install_staged_update()
        if result.get("state") == "installing":
            return False
    poll_and_execute()
    send_heartbeat()
    _sync_local_runs_to_backend()
    _check_offline_notification()
    return True


def run_agent(username, password):
    global _restart_requested
    _restart_requested = False
    initialize_agent_runtime()

    while not _restart_requested:
        agent_iteration(username, password)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
    else:
        username = _client_config.get("username", "")
        password = _client_config.get("password", "")
        if not username or not password:
            print("用法: python -m client.agent.main <用户名> <密码>")
            print("  Or configure credentials in client_config.json")
            sys.exit(1)
    run_agent(username, password)
