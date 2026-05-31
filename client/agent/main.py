import json
import os
import sys
import subprocess
import time
from datetime import datetime

import requests

from client.agent.executor import execute_script
from client.agent.local_server import start_local_server
from client.agent.script_parser import parse_script_config

# Load client config
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLIENT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "client_config.json")
_client_config = {}
if os.path.isfile(_CLIENT_CONFIG_PATH):
    try:
        with open(_CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            _client_config = json.load(f)
    except Exception:
        pass

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
    except Exception:
        pass
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
    print("Installing missing dependencies: {}".format(", ".join(missing)))
    try:
        result = subprocess.run(
            [python_bin, "-m", "pip", "install"] + missing,
            capture_output=True, timeout=300, text=True,
        )
        if result.returncode != 0:
            return "Dependency install failed: {}".format(result.stderr[:500])
        print("Dependencies installed successfully")
        return None
    except subprocess.TimeoutExpired:
        return "Dependency install timed out"
    except Exception as e:
        return "Dependency install error: {}".format(str(e))


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
    except Exception:
        pass
    return False


def _headers():
    return {"Authorization": "Bearer {}".format(_token)}


def _get_current_run_id():
    return _current_run_id


def poll_and_execute():
    global _current_run_id
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

        script_resp = requests.get(
            "{}/api/scripts/{}".format(BACKEND_URL, script_id),
            headers=_headers(),
            timeout=10,
        )
        if script_resp.status_code != 200:
            return

        script = script_resp.json()
        script_dir = os.path.join(_SCRIPTS_DIR, str(script_id), str(script["latest_version"]))
        os.makedirs(_LOGS_DIR, exist_ok=True)
        if not os.path.isdir(script_dir):
            requests.patch(
                "{}/api/runs/{}/status".format(BACKEND_URL, run_id),
                json={"status": "failed", "error_msg": "Script files not found"},
                headers=_headers(),
            )
            return

        log_path = os.path.join(_LOGS_DIR, "{}.log".format(run_id))

        # Apply environment config if set
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
                    print("Using environment: {} ({} vars, python={})".format(
                        env_cfg.get("name"), len(env_vars),
                        python_executable or "default"))
            except Exception as e:
                print("Failed to load environment: {}".format(e))

        # Check and install dependencies
        script_config = {}
        config_path = os.path.join(script_dir, "main.py")
        try:
            script_config = parse_script_config(config_path) or {}
        except Exception:
            pass

        if script_config:
            dep_error = ensure_dependencies(script_config, python_executable)
            if dep_error:
                requests.patch(
                    "{}/api/runs/{}/status".format(BACKEND_URL, run_id),
                    json={"status": "failed", "error_msg": dep_error},
                    headers=_headers(),
                )
                return

        # Determine timeout from config
        timeout = script_config.get("timeout", 600)

        requests.patch(
            "{}/api/runs/{}/status".format(BACKEND_URL, run_id),
            json={"status": "running"},
            headers=_headers(),
        )

        params = json.loads(run["params"]) if run.get("params") else {}
        result = execute_script(script_dir, params, log_path, timeout=timeout,
                                env_vars=env_vars or None, python_executable=python_executable)

        update = {"status": result["status"], "log_path": "storage/logs/{}.log".format(run_id)}
        if result.get("error"):
            update["error_msg"] = result["error"]
        if result.get("result"):
            update["result_files"] = json.dumps(result["result"])

        requests.patch(
            "{}/api/runs/{}/status".format(BACKEND_URL, run_id),
            json=update,
            headers=_headers(),
        )

    except Exception as e:
        if _current_run_id:
            try:
                requests.patch(
                    "{}/api/runs/{}/status".format(BACKEND_URL, _current_run_id),
                    json={"status": "failed", "error_msg": str(e)},
                    headers=_headers(),
                )
            except Exception:
                pass
    finally:
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


def check_for_update():
    """Check server for client version update. Returns True if update available."""
    local_version = _client_config.get("version", "0.0.0")
    try:
        resp = requests.get(
            "{}/api/settings/client-version".format(BACKEND_URL),
            timeout=10,
        )
        if resp.status_code == 200:
            remote_version = resp.json().get("version", "0.0.0")
            if _compare_versions(local_version, remote_version):
                print("=" * 50)
                print("  UPDATE AVAILABLE: {} -> {}".format(local_version, remote_version))
                print("  Contact admin to get the latest client version.")
                print("=" * 50)
                return True
    except Exception:
        pass
    return False


def run_agent(username, password):
    # Retry authentication in case backend is still starting
    for attempt in range(12):
        if authenticate(username, password):
            break
        if attempt < 11:
            print("Backend not ready, retrying in 5s... (attempt {}/{})".format(attempt + 1, 12))
            time.sleep(5)
        else:
            print("Authentication failed after 12 attempts")
            return

    print("Agent authenticated as {}, polling every {}s".format(username, POLL_INTERVAL))

    check_for_update()

    server_thread = start_local_server(LOCAL_PORT, _get_current_run_id)
    server_thread.daemon = True
    server_thread.start()

    while True:
        poll_and_execute()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
    else:
        username = _client_config.get("username", "")
        password = _client_config.get("password", "")
        if not username or not password:
            print("Usage: python -m client.agent.main <username> <password>")
            print("  Or configure credentials in client_config.json")
            sys.exit(1)
    run_agent(username, password)
