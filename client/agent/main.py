import io
import json
import logging
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime

import requests

from client.agent.local_server import start_local_server
from client.agent.script_parser import parse_script_config

logger = logging.getLogger(__name__)

# Load client config
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLIENT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "client_config.json")
_client_config = {}
if os.path.isfile(_CLIENT_CONFIG_PATH):
    try:
        with open(_CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
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
    _client_config.get("script_download_dir", os.path.join(_PROJECT_ROOT, "storage", "scripts")),
)
_LOGS_DIR = os.environ.get(
    "LOGS_DIR",
    os.path.join(os.path.dirname(_SCRIPTS_DIR), "logs"),
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

OFFLINE_NOTIFY_THRESHOLD_SEC = 30 * 60  # 30 min (design §5.9)
PENDING_REPORTS_FILE = os.path.join(os.path.dirname(_LOGS_DIR), ".pending_reports.json")


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


def _validate_run_params(param_defs, params):
    """Pre-execution parameter validation (design §5.2).

    Runs on the Agent (not the backend) because file/folder targets live on the
    client machine. Validates: required non-empty, file existence, folder existence
    (auto-creates if auto_create=True), number range, select options.
    Returns list of error strings.
    """
    errors = []
    param_map = {p["key"]: p for p in param_defs}

    for key, defn in param_map.items():
        val = params.get(key)
        ptype = defn.get("type", "text")
        label = defn.get("label", key)

        if defn.get("required") and (val is None or val == ""):
            errors.append("{}: 不能为空".format(label))
            continue

        if val is None or val == "":
            continue

        if ptype == "file":
            if not os.path.isfile(val):
                errors.append("{}: 文件不存在 - {}".format(label, val))
        elif ptype == "folder":
            auto_create = defn.get("auto_create", False)
            if not os.path.isdir(val):
                if auto_create:
                    try:
                        os.makedirs(val, exist_ok=True)
                        print("已自动创建目录: {}".format(val))
                    except OSError as e:
                        errors.append("{}: 目录自动创建失败 - {}".format(label, e))
                else:
                    errors.append("{}: 目录不存在 - {}".format(label, val))
        elif ptype == "number":
            try:
                num = float(val)
            except (TypeError, ValueError):
                errors.append("{}: 不是有效数字".format(label))
                continue
            if defn.get("min") is not None and num < defn["min"]:
                errors.append("{}: 值不能小于{}".format(label, defn["min"]))
            if defn.get("max") is not None and num > defn["max"]:
                errors.append("{}: 值不能大于{}".format(label, defn["max"]))
        elif ptype == "select":
            opts = defn.get("options", [])
            if opts and val not in opts:
                errors.append("{}: 无效选项".format(label))

    return errors


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
            return {"status": "failed", "error": "Timeout after {}s".format(info["timeout"]), "result": None}
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
                        result_value = eval(raw)
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
    agent_version = _client_config.get("version", "1.0.0")
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
    global _last_online_time, _offline_notified
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
_local_runs_file = os.path.join(os.path.dirname(_LOGS_DIR), ".local_runs.json")
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

    # Best-effort dependency install (offline: uses what's already cached in pip)
    if script_config:
        dep_error = ensure_dependencies(script_config)
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
        env_vars=env_vars, python_executable=None,
    )
    _local_run_proc = proc
    _local_run_info = {
        "local_run_id": local_run_id,
        "script_id": script_id,
        "script_version": latest_ver,
        "script_name": script_config.get("name"),
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
                        result_value = eval(raw)
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
        rec["result_files"] = json.dumps(result) if not isinstance(result, str) else result
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

            update = {
                "status": rec["status"],
                "log_path": "storage/logs/local_{}.log".format(local_run_id),
            }
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
        if run_id:
            update = {"status": result["status"]}
            # Report the real log path (relative to project root) so backend can find it —
            # previously hardcoded as "storage/logs/{id}.log" which didn't match reality.
            if actual_log_path:
                try:
                    update["log_path"] = os.path.relpath(actual_log_path, _PROJECT_ROOT)
                except ValueError:
                    update["log_path"] = actual_log_path
            if result.get("error"):
                update["error_msg"] = result["error"]
            if result.get("result"):
                update["result_files"] = json.dumps(result["result"])
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
                os.makedirs(os.path.dirname(script_dir), exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(dl_resp.content)) as zf:
                    zf.extractall(script_dir)
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
            dep_error = ensure_dependencies(script_config, python_executable)
            if dep_error:
                _report_run_status(run_id, {"status": "failed", "error_msg": dep_error})
                _current_run_id = None
                return

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
        _report_run_status(run_id, {"status": "running"})

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


def _check_and_apply_update(username="", password=""):
    """Check for client update; if available and package is staged, apply it.

    Returns True if update was triggered (process is about to exit and restart).
    Uses /api/agent/check-update endpoint. Update flow per design §5.8.
    """
    from client.agent.updater import check_and_apply_update as do_apply_update
    local_version = _client_config.get("version", "0.0.0")
    return do_apply_update(
        backend_url=BACKEND_URL,
        headers=_headers(),
        current_version=local_version,
        project_root=_PROJECT_ROOT,
        username=username,
        password=password,
    )


def run_agent(username, password):
    # Retry authentication in case backend is still starting
    for attempt in range(12):
        if authenticate(username, password):
            break
        if attempt < 11:
            print("后端未就绪,5 秒后重试... (第 {}/{} 次)".format(attempt + 1, 12))
            time.sleep(5)
        else:
            print("认证失败,已重试 12 次")
            return

    print("Agent 已认证为 {},每 {} 秒轮询一次".format(username, POLL_INTERVAL))

    # Register this agent with the backend (design §4.4)
    register_agent()

    # Load any pending run status reports from a previous run (design §5.9)
    _load_pending_reports()
    # Load local (offline) run history (survives restart)
    _load_local_runs()

    # Check and apply auto-update (may exit + restart the process)
    if _check_and_apply_update(username=username, password=password):
        return  # process is exiting; updater script will restart us

    server_thread = start_local_server(
        LOCAL_PORT,
        _get_current_run_id,
        list_local_scripts_fn=list_local_scripts,
        start_local_run_fn=start_local_run,
        list_local_runs_fn=list_local_runs,
        get_local_run_fn=get_local_run,
        get_local_run_log_fn=get_local_run_log,
        get_connection_status_fn=get_connection_status,
    )
    server_thread.daemon = True
    server_thread.start()

    while True:
        _flush_pending_reports()             # retry cached status reports first
        _check_local_runs()                  # advance offline run subprocess if any
        poll_and_execute()
        send_heartbeat()                     # liveness ping (design §5.1)
        _sync_local_runs_to_backend()        # back-fill offline runs to backend (§5.x offline)
        _check_offline_notification()        # pop system toast if disconnected (design §5.9)
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
