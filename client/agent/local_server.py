import json
import logging
import os
import threading
import winreg
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable

logger = logging.getLogger(__name__)


def _detect_browsers():
    """Scan registry and common paths for installed browsers."""
    results = []
    seen = set()

    for hive, flags in [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]:
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Clients\StartMenuInternet", 0, winreg.KEY_READ | flags)
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    i += 1
                    try:
                        sk = winreg.OpenKey(key, sub + r"\shell\open\command", 0, winreg.KEY_READ)
                        cmd, _ = winreg.QueryValueEx(sk, "")
                        winreg.CloseKey(sk)
                    except OSError:
                        continue
                    path = cmd.strip()
                    if path.startswith('"'):
                        path = path.split('"')[1]
                    elif " " in path:
                        path = path.split(" ")[0]
                    path = os.path.normpath(path)
                    if path.lower() in seen or not os.path.isfile(path):
                        continue
                    seen.add(path.lower())
                    try:
                        nk = winreg.OpenKey(key, sub, 0, winreg.KEY_READ)
                        name, _ = winreg.QueryValueEx(nk, "")
                        winreg.CloseKey(nk)
                    except OSError:
                        name = os.path.basename(path)
                    results.append({"name": name, "path": path})
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    common = [
        (r"Google\Chrome\Application\chrome.exe", "Google Chrome"),
        (r"Microsoft\Edge\Application\msedge.exe", "Microsoft Edge"),
        (r"Mozilla Firefox\firefox.exe", "Firefox"),
        (r"BraveSoftware\Brave-Browser\Application\brave.exe", "Brave"),
        (r"CentBrowser\Application\chrome.exe", "CentBrowser"),
        (r"360Chrome\Chrome\Application\360chrome.exe", "360 Chrome"),
        (r"SogouExplorer\SogouExplorer.exe", "Sogou Explorer"),
    ]
    program_dirs = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
    local_app = os.environ.get("LOCALAPPDATA", "")
    for rel, name in common:
        candidates = [os.path.join(d, rel) for d in program_dirs]
        if "Chrome" in rel or "Edge" in rel or "Brave" in rel:
            candidates.append(os.path.join(local_app, rel))
        for p in candidates:
            p = os.path.normpath(p)
            if p.lower() not in seen and os.path.isfile(p):
                seen.add(p.lower())
                results.append({"name": name, "path": p})
                break

    return results


class AgentHandler(BaseHTTPRequestHandler):
    get_status_fn = None
    get_version_fn = None
    # Offline execution callbacks (design §5.x offline mode): UI calls /local/* when backend unreachable
    list_local_scripts_fn = None     # () -> List[dict]
    start_local_run_fn = None        # (body: dict) -> dict (local_run record)
    list_local_runs_fn = None        # () -> List[dict]
    get_local_run_fn = None          # (local_run_id: str) -> dict | None
    get_local_run_log_fn = None      # (local_run_id: str) -> {"log": str}
    get_connection_status_fn = None  # () -> {"online": bool, "last_online_at": ..., "pending_sync": int}
    open_result_fn = None            # (path: str) -> {"success": bool, ...}
    get_update_status_fn = None       # () -> durable signed-update state
    check_update_fn = None            # () -> durable signed-update state
    install_update_fn = None          # () -> durable signed-update state
    get_runtime_info_fn = None        # () -> managed private-Python diagnostics

    def do_GET(self):
        if self.path == "/status":
            callback = type(self).get_status_fn
            run_id = callback() if callback else None
            version_callback = type(self).get_version_fn
            self._json({
                "running": run_id is not None,
                "run_id": run_id,
                "version": version_callback() if version_callback else None,
            })
        elif self.path == "/detect-browsers":
            self._json(_detect_browsers())
        elif self.path == "/local/runtime":
            callback = type(self).get_runtime_info_fn
            self._json(callback() if callback else {"status": "unavailable", "managed": True})
        elif self.path == "/local/scripts":
            callback = type(self).list_local_scripts_fn
            self._json(callback() if callback else [])
        elif self.path == "/local/runs":
            callback = type(self).list_local_runs_fn
            self._json(callback() if callback else [])
        elif self.path == "/local/connection":
            callback = type(self).get_connection_status_fn
            self._json(callback() if callback else {"online": False})
        elif self.path == "/local/update":
            callback = type(self).get_update_status_fn
            self._json(callback() if callback else {"state": "idle"})
        elif self.path.startswith("/local/runs/") and self.path.endswith("/log"):
            run_id = self.path[len("/local/runs/"):-len("/log")]
            try:
                callback = type(self).get_local_run_log_fn
                result = callback(run_id) if callback else {"log": ""}
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path.startswith("/local/runs/"):
            run_id = self.path[len("/local/runs/"):]
            try:
                callback = type(self).get_local_run_fn
                result = callback(run_id) if callback else None
                if result is None:
                    self._json({"error": "not found"}, 404)
                else:
                    self._json(result)
            except Exception as e:
                self._json({"error": str(e)}, 500)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/local/execute":
            data = self._read_json()
            if not data:
                return
            callback = type(self).start_local_run_fn
            if not callback:
                self._json({"error": "local execution not available"}, 503)
                return
            try:
                result = callback(data)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/local/results/open":
            data = self._read_json()
            if not data:
                return
            callback = type(self).open_result_fn
            if not callback:
                self._json({"success": False, "error": "本地打开功能不可用"}, 503)
                return
            try:
                result = callback(data.get("path"))
                self._json(result, 200 if result.get("success") else 400)
            except Exception as e:
                self._json({"success": False, "error": str(e)}, 500)
        elif self.path == "/local/update/check":
            if not self._consume_body():
                return
            callback = type(self).check_update_fn
            try:
                self._json(callback() if callback else {"state": "idle"})
            except Exception as e:
                self._json({"state": "idle", "error": str(e)}, 500)
        elif self.path == "/local/update/install":
            if not self._consume_body():
                return
            callback = type(self).install_update_fn
            try:
                result = callback() if callback else {"state": "idle", "error": "更新功能不可用"}
                self._json(result, 200 if result.get("state") in {"installing", "waiting-for-idle"} else 409)
            except Exception as e:
                self._json({"state": "idle", "error": str(e)}, 500)
        else:
            self._json({"error": "not found"}, 404)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            return json.loads(body)
        except (json.JSONDecodeError, ValueError, OSError):
            self._json({"error": "invalid json"}, 400)
            return None

    def _consume_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                self.rfile.read(length)
            return True
        except (ValueError, OSError):
            self._json({"error": "invalid request body"}, 400)
            return False

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def start_local_server(
    port,
    get_status_fn,
    get_version_fn=None,
    list_local_scripts_fn=None,
    start_local_run_fn=None,
    list_local_runs_fn=None,
    get_local_run_fn=None,
    get_local_run_log_fn=None,
    get_connection_status_fn=None,
    open_result_fn=None,
    get_update_status_fn=None,
    check_update_fn=None,
    install_update_fn=None,
    get_runtime_info_fn=None,
):
    AgentHandler.get_status_fn = get_status_fn
    AgentHandler.get_version_fn = get_version_fn
    AgentHandler.list_local_scripts_fn = list_local_scripts_fn
    AgentHandler.start_local_run_fn = start_local_run_fn
    AgentHandler.list_local_runs_fn = list_local_runs_fn
    AgentHandler.get_local_run_fn = get_local_run_fn
    AgentHandler.get_local_run_log_fn = get_local_run_log_fn
    AgentHandler.get_connection_status_fn = get_connection_status_fn
    AgentHandler.open_result_fn = open_result_fn
    AgentHandler.get_update_status_fn = get_update_status_fn
    AgentHandler.check_update_fn = check_update_fn
    AgentHandler.install_update_fn = install_update_fn
    AgentHandler.get_runtime_info_fn = get_runtime_info_fn
    server = HTTPServer(("127.0.0.1", port), AgentHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    return t
