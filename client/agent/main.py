import ast
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
import uuid

from client.runtime.task_store import TaskStore
from client.runtime.task_device import TaskDevice
from client.runtime.task_notifications import TaskNotifications
from client.runtime.execution_control import ExecutionGate, ExecutionController, prepare_environment, check_conditions
from client.runtime.process_tree import spawn_contained, ProcessTree, containment_name
from client.runtime.diagnostics import configure_application_logging, collect_diagnostics, update_effective_policy

import requests

from client.agent.local_server import start_local_server
from client.runtime.local_auth import get_or_create_agent_token
from client.agent.script_parser import parse_script_config
from shared.script_contract import extract_script_archive, validate_params
from shared.version import get_version
from client.runtime.profile import agent_ports, is_preview
from client.runtime.paths import ClientPaths
from client.runtime.python_runtime import PrivatePythonUnavailable, python_runtime_info

logger = logging.getLogger(__name__)

# Load client config
_CLIENT_PATHS = ClientPaths.from_environment()
_CLIENT_PATHS.ensure()
_PROJECT_ROOT = str(_CLIENT_PATHS.install_dir)
_CLIENT_CONFIG_PATH = str(_CLIENT_PATHS.config_file)
_LEGACY_CLIENT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "client_config.json")
_client_config = {}
_config_source = _CLIENT_CONFIG_PATH if os.path.isfile(_CLIENT_CONFIG_PATH) or is_preview() else _LEGACY_CLIENT_CONFIG_PATH
if os.path.isfile(_config_source):
    try:
        with open(_config_source, "r", encoding="utf-8") as f:
            _client_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("加载客户端配置失败: %s", e)

BACKEND_URL = (
    _client_config.get("server_url", "http://127.0.0.1:8765") if is_preview()
    else os.environ.get("BACKEND_URL", _client_config.get("server_url", "http://127.0.0.1:8000"))
)
POLL_INTERVAL = 5
LIVE_POLL_INTERVAL = 1
LOCAL_PORTS = agent_ports()

# Local paths for script storage and logs (decoupled from backend)
_SCRIPTS_DIR = (
    _client_config.get("script_download_dir") or str(_CLIENT_PATHS.scripts_dir) if is_preview()
    else os.environ.get("SCRIPTS_DIR", _client_config.get("script_download_dir") or str(_CLIENT_PATHS.scripts_dir))
)
_LOGS_DIR = str(_CLIENT_PATHS.logs_dir) if is_preview() else os.environ.get("LOGS_DIR", str(_CLIENT_PATHS.logs_dir))

_token = None
_user_id = None
_current_run_id = None

# Async execution tracking (avoid blocking poll loop)
_running_proc = None      # subprocess.Popen
_running_info = {}        # {run_id, script_dir, log_path, timeout, start_time}
_execution_start_lock = threading.Lock()  # local API and backend poll share one start gate

# Agent lifecycle state (design §4.4, §5.9)
_agent_id = None          # server-assigned agent id after register
_last_online_time = None  # last successful backend HTTP timestamp (disconnect detection)
_pending_reports = []     # cached run status updates that failed to send
_offline_notified = False  # avoid spamming disconnect notifications
_log_upload_offsets = {}  # run_id -> server-acknowledged UTF-8 byte offset
_pending_log_uploads = {}  # run_id -> local log path requiring a final retry
_last_update_check_time = 0
_update_worker = None
_update_worker_lock = threading.Lock()
_restart_requested = False
_shutdown_when_idle = False
_last_settings_sync_time = 0
_last_script_access_sync_time = 0
_task_notifications = None
PENDING_RETRY_BATCH = 1
LOG_CHUNK_BYTES = 256 * 1024

_CLIENT_SETTING_KEYS = {
    "server_url",
    "script_download_dir",
    "output_dir",
    "default_browser_path",
    "browser_debug_port",
    "proxy",
    "pip_index_url",
    "gitee_update_repository",
    "github_update_repository",
    "update_channel",
    "update_manifest_urls",
}

OFFLINE_NOTIFY_THRESHOLD_SEC = 30 * 60  # 30 min (design §5.9)
UPDATE_CHECK_INTERVAL_SEC = 6 * 60 * 60
SCRIPT_AUTHORIZATION_MAX_AGE_SEC = 7 * 24 * 60 * 60
PENDING_REPORTS_FILE = str(_CLIENT_PATHS.runs_dir / "pending_reports.json")
PENDING_LOG_UPLOADS_FILE = str(_CLIENT_PATHS.runs_dir / "pending_log_uploads.json")
SCRIPT_AUTHORIZATIONS_FILE = str(_CLIENT_PATHS.config_dir / "script_authorizations.json")


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
            _sync_task_notifications()
            return True
        if resp.status_code in (401, 403):
            _invalidate_script_authorizations()
    except (requests.RequestException, OSError):
        pass
    return False


def _headers():
    return {"Authorization": "Bearer {}".format(_token)}


def _upload_log_delta(run_id, log_path, force=False, agent_id=None):
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
            raw = f.read(LOG_CHUNK_BYTES)
    except OSError:
        return False

    if not raw:
        return True

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if (not force or offset + len(raw) < size) and e.reason == "unexpected end of data" and e.start > 0:
            raw = raw[:e.start]
            content = raw.decode("utf-8")
        else:
            content = raw.decode("utf-8", errors="replace")
    if not raw:
        return True

    try:
        payload = {"offset": offset, "content": content}
        if agent_id is not None:
            payload["agent_id"] = agent_id
        resp = requests.post(
            "{}/api/runs/{}/log/chunk".format(BACKEND_URL, run_id),
            json=payload,
            headers=_headers(),
            timeout=10,
        )
        data = resp.json()
        if resp.status_code == 200:
            _log_upload_offsets[run_id] = int(data["offset"])
            return _log_upload_offsets[run_id] >= size
        if resp.status_code == 409:
            detail = data.get("detail") or {}
            if "offset" in detail:
                _log_upload_offsets[run_id] = int(detail["offset"])
    except (requests.RequestException, OSError, KeyError, TypeError, ValueError):
        pass
    return False


def _finish_log_upload(run_id, log_path, agent_id=None):
    """Force the final delta and persist a retry when the backend is unavailable."""
    if _upload_log_delta(run_id, log_path, force=True, agent_id=agent_id):
        _pending_log_uploads.pop(run_id, None)
        _save_pending_log_uploads()
        return True
    _pending_log_uploads[run_id] = log_path
    _save_pending_log_uploads()
    return False


def _flush_pending_log_uploads():
    for run_id, path in list(_pending_log_uploads.items())[:PENDING_RETRY_BATCH]:
        complete = _upload_log_delta(run_id, path, force=True, agent_id=_agent_id)
        _pending_log_uploads.pop(run_id, None)
        if not complete:
            _pending_log_uploads[run_id] = path  # Rotate partial/failed uploads for fairness.
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
    if _controller is not None and _controller.active is not None:
        return _controller.active['body'].get('run_id', _controller.active['id'])
    return _current_run_id


def _start_script_subprocess(script_dir, params, log_path, timeout, env_vars=None, python_executable=None):
    """Start a script subprocess asynchronously (non-blocking). Returns Popen."""
    # Resolve absolute paths — the child subprocess runs with cwd=script_dir, so any
    # relative path passed in would be interpreted relative to a different cwd than the
    # parent Agent process. Abspath ensures parent and child see the same files.
    script_dir = os.path.abspath(script_dir)
    log_path = os.path.abspath(log_path)

    # Each process owns its parameter file, including during startup/cleanup races.
    params_file = None
    log_file = None
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="params-", suffix=".json",
            dir=os.path.dirname(log_path), delete=False,
        ) as f:
            params_file = f.name
            json.dump(params, f, ensure_ascii=False)

        code = (
            "import sys, json, os; "
            "sys.path.insert(0, sys.argv[1]); "
            "_pf = sys.argv[3]; "
            "_params = json.load(open(_pf, encoding='utf-8')); "
            "from main import main; "
            "result = main(**_params); "
            "sys.stdout.flush(); "
            "sys.stdout.buffer.write(('\\n__RESULT__:' + repr(result) + '\\n').encode('utf-8')); "
            "sys.stdout.buffer.flush()"
        )

        proc_env = os.environ.copy()
        # UTF-8 and unbuffered output keep Windows logs readable and live.
        proc_env["PYTHONIOENCODING"] = "utf-8"
        proc_env["PYTHONUNBUFFERED"] = "1"
        if env_vars:
            proc_env.update(env_vars)

        python_bin = python_executable or sys.executable
        # The child writes bytes; text mode would corrupt Chinese output.
        log_file = open(log_path, "wb")
        proc = spawn_contained(
            [python_bin, "-c", code, script_dir, log_path, params_file],
            tree_name=containment_name(_CLIENT_PATHS, 'script'),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=script_dir,
            env=proc_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        if log_file is not None:
            log_file.close()
        if params_file is not None:
            try:
                os.remove(params_file)
            except OSError:
                logger.warning("无法清理未启动任务的参数文件")
        raise
    # Store log_file so it can be closed later
    proc._log_file = log_file
    proc._params_file = params_file
    return proc


def _notify_execution_result(script_name, status, error=None):
    """Notify completion without allowing notification failures to affect task state."""
    try:
        from client.agent.notifier import show_system_notification
        name = script_name or "脚本"
        if status == "success":
            message = "{} 执行完成".format(name)
        elif status == "cancelled":
            message = "{} 已取消".format(name)
        else:
            message = "{} 执行失败：{}".format(name, error or "未知错误")
        show_system_notification("AutoScript Hub", message)
    except Exception as exc:
        logger.warning("通知失败: %s", exc)


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
        if resp.status_code in (401, 403):
            _invalidate_script_authorizations()
            _token = None
            _sync_task_notifications()
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
    batch = _pending_reports[:PENDING_RETRY_BATCH]
    for item in batch:
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
    _pending_reports = _pending_reports[len(batch):] + remaining
    _save_pending_reports()


def _report_run_status(run_id, update):
    """Report run status to backend. Cache locally on failure for later retry (design §5.9)."""
    global _last_online_time
    update = dict(update)
    if _agent_id is not None:
        update.setdefault("agent_id", _agent_id)
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


def _report_run_failure(run_id, error, script_name=None):
    _report_run_status(run_id, {"status": "failed", "error_msg": error})
    _notify_execution_result(script_name, "failed", error)


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
        temporary = _local_runs_file + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(_local_runs, f, ensure_ascii=False)
        os.replace(temporary, _local_runs_file)
        return True
    except OSError as e:
        logger.warning("保存本地执行记录失败: %s", e)
        return False


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


def _load_authorized_script_ids():
    """Return a current server-confirmed authorization snapshot; fail closed otherwise."""
    try:
        with open(SCRIPT_AUTHORIZATIONS_FILE, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if payload.get("server_url") != BACKEND_URL.rstrip("/"):
            return set()
        configured_username = str(_client_config.get("username") or "").strip()
        if payload.get("username") != configured_username:
            return set()
        synced_at = datetime.fromisoformat(str(payload.get("synced_at") or ""))
        age = time.time() - synced_at.timestamp()
        if age < -300 or age > SCRIPT_AUTHORIZATION_MAX_AGE_SEC:
            return set()
        return {int(item) for item in payload.get("script_ids", [])}
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return set()


def _write_script_authorizations(script_ids):
    payload = {
        "server_url": BACKEND_URL.rstrip("/"),
        "username": str(_client_config.get("username") or "").strip(),
        "user_id": _user_id,
        "script_ids": sorted(set(int(item) for item in script_ids)),
        "synced_at": datetime.now().isoformat(),
    }
    path = Path(SCRIPT_AUTHORIZATIONS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _invalidate_script_authorizations():
    try:
        _write_script_authorizations([])
    except (OSError, ValueError, TypeError):
        pass


def _sync_script_authorizations():
    """Persist group authorization so revoked cached scripts stay unavailable offline."""
    if not _token:
        return False
    try:
        response = requests.get(
            "{}/api/scripts/authorized-ids".format(BACKEND_URL),
            headers=_headers(),
            timeout=10,
        )
        if response.status_code in (401, 403):
            _write_script_authorizations([])
            return True
        if response.status_code != 200:
            return False
        _write_script_authorizations(response.json())
        return True
    except (requests.RequestException, OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def list_local_scripts():
    """Scan local script cache; return [{id, latest_version, name, ...}].

    Each script_id subdirectory under _SCRIPTS_DIR contains version subdirs.
    For each, we parse main.py's config() to surface metadata to the offline UI.
    """
    result = []
    authorized_ids = _load_authorized_script_ids()
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
        if script_id not in authorized_ids:
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
            "latest_semantic_version": config.get("version"),
            "name": config.get("name", "Script #{}".format(script_id)),
            "description": config.get("description", ""),
            "category": config.get("category", ""),
            "config": config,
            "config_json": json.dumps(config, ensure_ascii=False),
            "local_only": True,
        })
    return result


def list_local_runs():
    """Return all local run records, newest first."""
    items = [dict(record) for record in _local_runs.values()]
    if _controller is not None and _controller.active is not None:
        active = _controller.active
        for item in items:
            if item.get('local_run_id') == active['id']:
                item['status'] = active['state']
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
        if not r.get("synced") and r.get("status") in ("success", "failed", "cancelled")
    )
    return {
        "online": online,
        "last_online_at": _last_online_time,
        "pending_sync_count": pending_sync,
        "agent_id": _agent_id,
    }


def _sync_local_runs_to_backend():
    if not _execution_start_lock.acquire(blocking=False):
        return
    try:
        _sync_local_runs_locked()
    finally:
        _execution_start_lock.release()


# 1.3 execution entry points: all sources use the same durable controller.
_task_store = None
_task_device = None
_controller = None
_lifetime_gate = None
_task_init_lock = threading.RLock()


def _task_request(method, route, body=None, extra_headers=None):
    if not _token:
        raise RuntimeError('设备操作需要在线认证')
    response = requests.request(method, BACKEND_URL.rstrip('/') + route,
                                json=body, headers={**_headers(), **(extra_headers or {})}, timeout=10)
    response.raise_for_status()
    return response.json()


def _initialize_tasks():
    global _task_store, _task_device, _controller, _lifetime_gate
    with _task_init_lock:
        if _controller is not None:
            return
        try:
            _initialize_tasks_locked()
        except BaseException:
            if _task_store is not None:
                _task_store.close()
            if _lifetime_gate is not None:
                _lifetime_gate.close()
            _task_store = _task_device = _controller = _lifetime_gate = None
            raise


def _initialize_tasks_locked():
    global _task_store, _task_device, _controller, _lifetime_gate
    if _controller is not None:
        return
    _lifetime_gate = ExecutionGate(_CLIENT_PATHS.runs_dir / 'execution.lock')
    # Reopen named jobs: lifetime lock alone does not prove asynchronous kill-on-close finished.
    if os.name == 'nt':
        for kind in ('prepare', 'script'):
            tree = ProcessTree(containment_name(_CLIENT_PATHS, kind))
            try:
                tree.stop()
                tree.confirm_stopped()
            finally:
                tree.close()
    _task_store = TaskStore(_CLIENT_PATHS.runs_dir / 'tasks.sqlite3')
    _task_device = TaskDevice(_CLIENT_PATHS.config_dir / 'task-device.bin', _task_request,
                              get_version(), BACKEND_URL.rstrip('/') + '|' + str(_client_config.get('username', '')))
    for attempt in _task_store.recover():
        _task_store.enqueue_report('remote:' + attempt['execution_id'],
                                  '/executions/' + attempt['execution_id'] + '/report',
                                  {'attempt_id': attempt['attempt_id'], 'state': 'unknown',
                                   'stopped': True, 'error_msg': 'Agent 重启，业务结果不确定；禁止自动重跑'})
    for record in _local_runs.values():
        if record.get('status') in ('running', 'preparing'):
            record.update(status='unknown', error_msg='Agent 重启，业务结果不确定；禁止自动重跑')
    _save_local_runs()
    _controller = ExecutionController(_task_store, _prepare_task, _spawn_task, _complete_task,
                                     lambda item: _task_device.call('POST', '/executions/' +
                                         str(item['body']['execution_id']) + '/start',
                                         {'attempt_id': item['body']['attempt_id']}).get('can_start') is True)


def _fixed_script(body, local=False):
    if not isinstance(body, dict):
        raise ValueError('任务必须是对象')
    script_id, version = body.get('script_id'), body.get('script_version')
    if any(type(v) is not int or v < 1 for v in (script_id, version)):
        raise ValueError('必须指定数值 script_id 与固定 script_version')
    if local and script_id not in _load_authorized_script_ids():
        raise ValueError('脚本授权已失效，请联网刷新市场权限')
    directory = os.path.join(_SCRIPTS_DIR, str(script_id), str(version))
    if not os.path.isfile(os.path.join(directory, 'main.py')):
        if local:
            raise ValueError('指定版本未缓存')
        response = requests.get('{}/api/scripts/{}/download?version={}'.format(BACKEND_URL, script_id, version),
                                headers=_headers(), timeout=30)
        response.raise_for_status()
        _install_downloaded_script(response.content, directory)
    config = parse_script_config(os.path.join(directory, 'main.py'))
    if not isinstance(config, dict):
        raise ValueError('无法解析固定版本脚本配置')
    params = body.get('params', {})
    if isinstance(params, str):
        params = json.loads(params)
    if not isinstance(params, dict):
        raise ValueError('params 必须是对象')
    errors = _validate_run_params(config.get('params', []), params)
    if errors:
        raise ValueError('参数校验失败: ' + '; '.join(errors))
    body['params'] = params
    return directory, config


def _prepare_task(item):
    body = item['body']
    if item['source'] == 'remote':
        execution_id = body['execution_id']
        attempt = _task_store.attempt(execution_id, body)
        body['attempt_id'] = attempt
        try:
            claimed = _task_device.call('POST', '/executions/' + str(execution_id) + '/claim', {'attempt_id': attempt})
        except requests.HTTPError as exc:
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                body['claim_rejected'] = True
                _task_store.attempt_state(execution_id, 'rejected', body)
            raise
        if claimed.get('state') != 'claimed':
            raise RuntimeError('领取状态不允许启动')
        body.update(claimed, execution_id=execution_id, attempt_id=attempt)
        _task_store.attempt_state(execution_id, 'claimed', body)
        timeout = body.get('timeout_seconds')
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise ValueError('远程任务超时无效')
        item['deadline'] = item['started_monotonic'] + timeout
    elif item['source'] == 'legacy':
        run_id = body['run_id']
        claimed = _task_request('POST', '/api/runs/{}/claim'.format(run_id), {'agent_id': _agent_id})
        body.update(claimed, run_id=run_id)
    directory, config = _fixed_script(body, local=item['source'] == 'local')
    if item['source'] == 'legacy':
        timeout = config.get('timeout', 600)
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise ValueError('脚本超时配置无效')
        item['deadline'] = item['started_monotonic'] + timeout
    from client.agent.local_server import _detect_browsers
    check_conditions(body, _detect_browsers)
    remaining = item['deadline'] - time.monotonic()
    if remaining <= 0 or item['cancel'].is_set():
        raise InterruptedError('准备已取消或超时')
    executable = prepare_environment(config, _CLIENT_PATHS, _client_config.get('pip_index_url') or None,
                                     not get_connection_status()['online'], item['cancel'], timeout=remaining)
    item.update(script_dir=directory, script_name=config.get('name'),
                log_path=os.path.join(_LOGS_DIR, item['id'] + '.log'))
    return executable


def _safe_legacy_environment(body):
    # Keep explicit application settings, never remote interpreter/loader overrides.
    env = {}
    if body.get('environment_id'):
        value = _task_request('GET', '/api/environments/' + str(int(body['environment_id'])))
        for key, target in [('browser_port', 'BROWSER_PORT'), ('browser_path', 'BROWSER_PATH'),
                            ('output_dir', 'OUTPUT_DIR'), ('proxy', 'http_proxy')]:
            if value.get(key):
                env[target] = str(value[key])
        if 'http_proxy' in env:
            env['https_proxy'] = env['http_proxy']
    return env


def _spawn_task(item, executable):
    if item['source'] == 'local':
        record = _local_runs[item['id']]
        record.update(status='running', log_path=item['log_path'], script_name=item.get('script_name'))
        if not _save_local_runs():
            raise RuntimeError('启动状态无法持久化')
    env = _safe_legacy_environment(item['body']) if item['source'] == 'legacy' else None
    _controller._guard(item)
    return _start_script_subprocess(item['script_dir'], item['body']['params'], item['log_path'],
                                    item['body'].get('timeout_seconds', 600), env_vars=env,
                                    python_executable=executable)


def _log_tail(path):
    try:
        with open(path, 'rb') as stream:
            start = max(0, stream.seek(0, 2) - 65536)
            stream.seek(start)
            raw = stream.read(65536)
            if start:
                # 丢弃首条残缺行，避免截断掉凭据字段名后只上传其值。
                raw = raw.split(b'\n', 1)[1] if b'\n' in raw else b''
            return raw.decode('utf-8', errors='ignore')
    except (OSError, TypeError):
        return ''


def _complete_task(item):
    from client.runtime.execution_output import bounded_execution_output
    body, state = item['body'], item['state']
    try:
        tail = _log_tail(item.get('log_path'))
    except Exception:
        tail = ''
        logger.warning('无法读取结果日志；保留执行终态')
    files = []
    try:
        for line in tail.splitlines():
            if line.startswith('__RESULT__:'):
                files = [v['path'] for v in _normalize_result_files(_parse_result_literal(line[11:]), item.get('script_dir'))]
    except Exception:
        logger.warning('忽略无效脚本结果标记；保留执行终态')
    output = bounded_execution_output(item.get('error_msg'), files, tail)
    files = output['result_files']
    if item['source'] == 'remote':
        if not body.get('attempt_id') or body.get('claim_rejected'):
            return  # No claim exists; do not retain an impossible attempt report.
        payload = {'attempt_id': body['attempt_id'], 'state': state, 'stopped': True, **output}
        _task_store.finish_attempt(body['execution_id'], body, payload)
    elif item['source'] == 'legacy':
        if item.get('log_path'):
            try:
                _finish_log_upload(body['run_id'], item['log_path'], agent_id=_agent_id)
            except Exception:
                logger.warning('日志上传异常；继续记录执行终态')
        _task_store.enqueue_report('legacy:' + str(body['run_id']), '/api/runs/' + str(body['run_id']) + '/status',
                                   {'status': state, 'error_msg': output['error_msg'],
                                    'result_files': json.dumps(files), 'agent_id': _agent_id})
    else:
        rec = _local_runs.get(item['id'])
        if rec is not None:
            finished = time.time()
            rec.update(status=state, finished_at=finished, error_msg=output['error_msg'],
                       duration_sec=max(0, int(finished - rec['started_at'])),
                       log_path=item.get('log_path'), result_files=files)
            if not _save_local_runs():
                raise RuntimeError('完成记录持久化失败，保留执行槽')
    _notify_execution_result(item.get('script_name'), state, item.get('error_msg'))


def start_local_run(req, *, event_id=None):
    if not _execution_start_lock.acquire(blocking=False):
        return {'error': 'another task is running'}
    try:
        if _controller is not None and _controller.active is not None:
            return {'error': 'another task is running'}
        if _running_proc is not None or _local_run_proc is not None:
            return {'error': 'another task is running'}
        return _submit_local_run(req, event_id=event_id)
    except Exception as exc:
        return {'error': str(exc)}
    finally:
        _execution_start_lock.release()


def _submit_local_run(req, *, event_id=None):
    if _shutdown_when_idle:
        return {'error': 'Agent 正在退出，不能启动新任务'}
    body = dict(req)
    if body.get('script_id') not in _load_authorized_script_ids():
        return {'error': '脚本授权已失效，请联网刷新市场权限'}
    _initialize_tasks()
    if 'env_vars' in body or 'python_executable' in body:
        raise ValueError('本机任务不接受环境变量或解释器覆盖')
    if set(body) - {'script_id', 'script_version', 'params', 'timeout_seconds', 'requires_desktop',
                    'requires_browser', 'name', 'trigger'}:
        raise ValueError('本机任务包含不允许的字段')
    if 'script_version' not in body:
        match = next((s for s in list_local_scripts() if s['id'] == body.get('script_id')), None)
        if match:
            body['script_version'] = match['latest_version']
    _, config = _fixed_script(body, local=True)
    body.setdefault('timeout_seconds', config.get('timeout', 600))
    ident = event_id or 'L' + str(uuid.uuid4())
    with _controller.lock:
        if _controller.active is not None:
            return {'error': 'another task is running'}
        record = {'local_run_id': ident, 'request_id': str(uuid.uuid4()), **body,
                  'status': 'preparing', 'started_at': time.time(), 'finished_at': None, 'synced': False}
        _local_runs[ident] = record
        if not _save_local_runs():
            _local_runs.pop(ident, None)
            raise RuntimeError('执行意图无法持久化')
        try:
            result = _controller.submit(ident, body)
        except Exception as exc:
            if event_id is not None:
                _local_runs.pop(ident, None)  # No execution was accepted; event owns skipped/cancelled fact.
            else:
                record.update(status='failed', error_msg=str(exc), finished_at=time.time())
            _save_local_runs()
            raise
        return record if 'error' not in result else result


def _check_local_runs():
    if _controller is None:
        return
    _task_store.tick()
    if _controller.active is None and not _shutdown_when_idle:
        for event in _task_store.queued():
            try:
                result = start_local_run(event['body'], event_id=event['id'])
                if result.get('error') and result['error'] != 'another task is running':
                    _task_store.fail_queued(event['id'], result['error'])
            except Exception as exc:
                _task_store.fail_queued(event['id'], str(exc))


def poll_and_execute():
    if not _execution_start_lock.acquire(blocking=False):
        return
    try:
        if _running_proc is not None or _local_run_proc is not None:
            return
        _poll_tasks_once()
    finally:
        _execution_start_lock.release()


def _poll_tasks_once():
    if _controller is None or _shutdown_when_idle:
        return
    def send(route, body):
        try:
            if route.startswith('/api/runs/'):
                _task_request('PATCH', route, body)
            else:
                _task_device.call('POST', route, body)
                execution_id = route.split('/')[2]
                _task_store.attempt_state(execution_id, 'reported')
            return True
        except Exception:
            return False
    try:
        if not _task_device.registered:
            _task_device.register()
        _task_device.call('POST', '/heartbeat', {})
        _sync_task_notifications()
    except Exception as exc:
        logger.debug('任务设备心跳暂不可用: %s', type(exc).__name__)
    _task_store.flush(send)  # Legacy reports must still drain against pre-1.3 servers.
    try:
        pending = _task_device.call('GET', '/pending')
        active = _controller.active
        for execution in pending:
            ident = 'R' + str(execution['id'])
            if active and active['id'] == ident and execution['state'] == 'cancel_requested':
                _controller.cancel(ident)
            if _controller.active is None and execution['state'] == 'queued':
                if any(a['execution_id'] == str(execution['id']) for a in _task_store.attempts()):
                    continue
                _controller.submit(ident, {**execution, 'execution_id': execution['id']}, 'remote')
                return
    except Exception as exc:
        logger.debug('任务设备同步暂不可用: %s', type(exc).__name__)
    if _controller.active is not None:
        item = _controller.active
        if item['source'] == 'legacy':
            try:
                if item.get('log_path'):
                    _upload_log_delta(item['body']['run_id'], item['log_path'], agent_id=_agent_id)
                run = _task_request('GET', '/api/runs/' + str(item['body']['run_id']))
                if run.get('status') == 'cancelled':
                    _controller.cancel(item['id'])
            except Exception:
                pass
        return
    if not _agent_id:
        return
    try:
        runs = _task_request('GET', '/api/runs?status=pending&limit=1&mine_only=true')
        if runs:
            run = runs[0]
            if any(rec.get('backend_run_id') == run['id'] for rec in _local_runs.values()):
                return  # Pre-1.3 history imports must never become executable work.
            ident = 'B' + str(run['id'])
            if any(e['id'] == ident for e in _task_store.events()):
                return
            _controller.submit(ident, {**run, 'run_id': run['id']}, 'legacy')
    except Exception as exc:
        logger.debug('旧任务轮询暂不可用: %s', type(exc).__name__)


def _sync_local_runs_locked():
    if not get_connection_status()['online']:
        return
    candidates = [(ident, rec) for ident, rec in list(_local_runs.items())
                  if not rec.get('synced') and rec.get('status') in ('success', 'failed', 'cancelled')]
    candidates.sort(key=lambda pair: pair[1].get('last_import_attempt', 0))
    for ident, rec in candidates[:1]:  # Bound network work so heartbeat cannot be starved by history.
        try:
            rec['last_import_attempt'] = time.time()
            if rec.get('backend_run_id') is not None:
                remote = _task_request('GET', '/api/runs/' + str(rec['backend_run_id']))
                if (remote.get('script_id') != rec['script_id'] or
                        remote.get('script_version') != rec['script_version'] or
                        remote.get('agent_id') not in (None, _agent_id)):
                    rec['sync_error'] = '旧导入记录身份不匹配，需要人工核对'
                elif remote.get('status') in ('success', 'failed', 'cancelled', 'running'):
                    if remote.get('status') == 'running' and (not _agent_id or remote.get('agent_id') != _agent_id):
                        rec['sync_error'] = '旧记录不属于当前 Agent，需要人工核对'
                    else:
                        logs_synced = True
                        try:
                            if rec.get('log_path'):
                                logs_synced = _finish_log_upload(rec['backend_run_id'], rec['log_path'], agent_id=_agent_id)
                        except Exception:
                            logs_synced = False
                        if remote.get('status') == 'running':
                            _task_request('PATCH', '/api/runs/' + str(rec['backend_run_id']) + '/status',
                                          {'status': rec['status'], 'agent_id': _agent_id,
                                           'error_msg': rec.get('error_msg'),
                                           'result_files': rec['result_files'] if isinstance(rec.get('result_files'), str)
                                                           else json.dumps(rec.get('result_files') or [])})
                        rec['synced'] = logs_synced  # Never overwrite an already-terminal remote result.
                else:
                    rec['sync_error'] = '旧导入记录尚未结束，需要人工核对；不会重新执行'
                _save_local_runs()
                continue
            if not _task_device or not _task_device.registered:
                continue  # Old servers may reconcile existing IDs, but cannot import new history.
            if not rec.get('import_payload'):
                rec.setdefault('request_id', str(uuid.uuid4()))
                files = rec.get('result_files') or []
                if isinstance(files, str):
                    files = json.loads(files)
                files = [v if isinstance(v, str) else v['path'] for v in files]
                payload = {k: rec[k] for k in ('request_id', 'script_id', 'script_version', 'status')}
                from client.runtime.execution_output import bounded_execution_output
                payload.update(device_id=_task_device.registered['id'], params=rec.get('params') or {},
                               started_at=datetime.fromtimestamp(rec['started_at'], timezone.utc).isoformat(),
                               finished_at=datetime.fromtimestamp(rec['finished_at'], timezone.utc).isoformat(),
                               **bounded_execution_output(rec.get('error_msg'), files, _log_tail(rec.get('log_path'))))
                rec['import_payload'] = json.loads(json.dumps(payload))
            if not _save_local_runs():
                continue
            payload = rec['import_payload']
            result = _task_request('POST', '/api/runs/import-local', payload,
                                   {'X-Device-Token': _task_device.identity['device_secret']})
            rec.update(synced=True, backend_run_id=result['run_id'])
            _save_local_runs()
        except (requests.RequestException, OSError, ValueError, KeyError, TypeError):
            logger.debug('本机完成历史导入暂不可用: %s', ident)


def _local_task_api(method, path, body=None):
    _initialize_tasks()
    if method == 'GET':
        if path == '/local/schedules':
            return _task_store.tasks()
        if path == '/local/schedule-events':
            return [dict(e, task_name=e['body'].get('name') or e['body'].get('task_name'),
                         script_id=e['body'].get('script_id'), script_version=e['body'].get('script_version'),
                         run_id=e['body'].get('run_id'),
                         local_run_id=e['id'] if e['id'] in _local_runs else None) for e in _task_store.events()]
        if path == '/local/task-device':
            return _task_device.public()
        if path == '/local/device-grants':
            return _task_device.grants() if _task_device.registered else []
        if path == '/local/diagnostics':
            return collect_diagnostics(_CLIENT_PATHS, _agent_id, get_connection_status()['online'])
    if method == 'POST':
        if path == '/local/schedules':
            allowed = {'name', 'script_id', 'script_version', 'params', 'trigger', 'timeout_seconds',
                       'requires_desktop', 'requires_browser'}
            if set(body) - allowed:
                raise ValueError('任务包含不允许的字段')
            _fixed_script(body, local=True)
            timeout = body.get('timeout_seconds', 600)
            if type(timeout) is not int or not 1 <= timeout <= 86400:
                raise ValueError('无效超时')
            for key in ('requires_desktop', 'requires_browser'):
                if type(body.get(key, False)) is not bool:
                    raise ValueError('运行条件必须是布尔值')
            return _task_store.create(body)
        parts = path.strip('/').split('/')
        if len(parts) == 4 and parts[:2] == ['local', 'schedules'] and parts[3] == 'action':
            with _controller.lock:
                result = _task_store.action(parts[2], body)
                active = _controller.active
                if body.get('action') in ('pause', 'delete') and active is not None:
                    if any(e['id'] == active['id'] and e['task_id'] == parts[2] for e in _task_store.events()):
                        _controller.cancel(active['id'])
                return result
        if len(parts) == 4 and parts[:2] == ['local', 'device-grants'] and parts[3] == 'decision':
            return _task_device.decision(parts[2], body)
        if len(parts) == 4 and parts[:2] == ['local', 'runs'] and parts[3] == 'cancel':
            return _controller.cancel(parts[2])
    raise ValueError('未知本机任务接口')


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
    """Check public signed sources for an available update without downloading it."""
    from client.agent.updater import check_and_stage_update
    local_version = get_version()
    return check_and_stage_update(
        current_version=local_version,
        runtime_is_idle=_runtime_is_idle,
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


def _run_update_install_worker():
    global _restart_requested
    from client.agent.updater import install_staged_update

    try:
        result = install_staged_update(
            current_version=get_version(),
            runtime_is_idle=_runtime_is_idle,
        )
        if result.get("state") == "installing":
            _restart_requested = True
            if _task_notifications is not None:
                _task_notifications.stop()
    except Exception:
        logger.exception("后台更新下载或安装启动失败")


def _install_staged_update():
    """Start download/verification in the background and return immediately."""
    global _update_worker
    if is_preview():
        return _get_update_status()
    with _update_worker_lock:
        if _update_worker is not None and _update_worker.is_alive():
            return _get_update_status()
        persisted = _get_update_status()
        _update_worker = threading.Thread(
            target=_run_update_install_worker,
            name="client-update-worker",
            daemon=True,
        )
        _update_worker.start()
        return {
            **persisted,
            "state": "downloading",
            "version": persisted.get("version"),
            "error": None,
        }


def request_shutdown_when_idle():
    """Stop accepting work and exit after all current scripts finish."""
    global _shutdown_when_idle
    _shutdown_when_idle = True
    if _task_notifications is not None:
        _task_notifications.stop()


def _runtime_is_idle():
    return (_controller is None or _controller.active is None) and _running_proc is None and _local_run_proc is None


def initialize_agent_runtime():
    """Load cached state and start the local API before any backend connection."""
    _load_pending_reports()
    _load_pending_log_uploads()
    _load_local_runs()
    configure_application_logging('agent', _CLIENT_PATHS)
    _initialize_tasks()
    server_thread = start_local_server(
        LOCAL_PORTS,
        _get_current_run_id,
        get_version_fn=get_version,
        api_token=get_or_create_agent_token(),
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
        request_shutdown_fn=request_shutdown_when_idle,
        task_api_fn=_local_task_api,
    )
    server_thread.daemon = True
    server_thread.start()
    return server_thread


def agent_iteration(username, password):
    """Run one online/offline Agent loop iteration without exiting on disconnect."""
    global _last_update_check_time, _restart_requested, _last_settings_sync_time
    global _last_script_access_sync_time

    _check_local_runs()  # Scheduler and process worker remain functional with no network.
    if not _token:
        if not authenticate(username, password):
            update_effective_policy({})
            _check_offline_notification()
            return False
        print("Agent 已认证为 {},每 {} 秒轮询一次".format(username, POLL_INTERVAL))
        register_agent()

    heartbeat_ok = send_heartbeat()  # Business liveness precedes retries/settings traffic.
    _sync_task_notifications()
    now = time.time()
    if _last_update_check_time == 0 or now - _last_update_check_time >= UPDATE_CHECK_INTERVAL_SEC:
        _last_update_check_time = now
        _check_and_stage_update()
    if now - _last_settings_sync_time >= 60:
        try:
            update_effective_policy(_task_request('GET', '/api/settings/diagnostics/effective'))
        except Exception:
            update_effective_policy({})
        if _sync_client_settings():
            _last_settings_sync_time = now
    if now - _last_script_access_sync_time >= 60:
        if _sync_script_authorizations():
            _last_script_access_sync_time = now

    _check_local_runs()
    poll_and_execute()
    _flush_pending_reports()
    _flush_pending_log_uploads()
    _sync_local_runs_to_backend()
    _check_offline_notification()
    return heartbeat_ok


def _sync_task_notifications():
    if _task_notifications is None:
        return
    account = str(_client_config.get('username', ''))
    scope = BACKEND_URL.rstrip('/') + '|' + account
    identity = _task_device.notification_identity(scope) if _task_device is not None else None
    if not _token or identity is None or _shutdown_when_idle or _restart_requested:
        _task_notifications.configure()
    else:
        _task_notifications.configure(BACKEND_URL, (account, _user_id), _token, *identity)


def _next_poll_interval():
    return LIVE_POLL_INTERVAL if not _runtime_is_idle() else POLL_INTERVAL


def run_agent(username, password):
    global _restart_requested, _shutdown_when_idle, _task_notifications
    _restart_requested = False
    _shutdown_when_idle = False
    initialize_agent_runtime()
    _task_notifications = TaskNotifications()
    _task_notifications.start()
    try:
        while not _restart_requested:
            _sync_task_notifications()
            agent_iteration(username, password)
            _sync_task_notifications()
            if _shutdown_when_idle and _runtime_is_idle():
                print("GUI 已关闭，Agent 已完成当前任务并退出")
                break
            _task_notifications.wait(_next_poll_interval())
    finally:
        _task_notifications.stop()
        _task_notifications = None


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
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
