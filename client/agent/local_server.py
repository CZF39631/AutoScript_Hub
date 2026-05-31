import json
import os
import shutil
import subprocess
import sys
import threading
import winreg
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable


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


def _detect_python_versions():
    """Detect installed Python versions via py launcher and registry."""
    results = []
    seen = set()

    # py --list
    try:
        proc = subprocess.run(
            ["py", "--list"], capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                version = None
                path = None
                for p in line.split():
                    if p.startswith("-V:"):
                        version = p[3:]
                    if "python" in p.lower():
                        path = p
                if path and path.lower() not in seen and os.path.isfile(path):
                    seen.add(path.lower())
                    results.append({"version": version or "unknown", "path": os.path.normpath(path)})
    except Exception:
        pass

    # Registry: SOFTWARE\Python\PythonCore
    for hive, flags in [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]:
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Python\PythonCore", 0, winreg.KEY_READ | flags)
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    i += 1
                    try:
                        ik = winreg.OpenKey(key, sub + r"\InstallPath", 0, winreg.KEY_READ)
                        ipath, _ = winreg.QueryValueEx(ik, "")
                        winreg.CloseKey(ik)
                    except OSError:
                        continue
                    exe = os.path.join(ipath, "python.exe")
                    if os.path.isfile(exe) and exe.lower() not in seen:
                        seen.add(exe.lower())
                        results.append({"version": sub, "path": os.path.normpath(exe)})
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    # sys.executable as fallback
    if sys.executable.lower() not in seen:
        seen.add(sys.executable.lower())
        results.append({
            "version": "{}.{}.{}".format(*sys.version_info[:3]),
            "path": os.path.normpath(sys.executable),
        })

    return results


class AgentHandler(BaseHTTPRequestHandler):
    get_status_fn = None

    def do_GET(self):
        if self.path == "/status":
            run_id = self.get_status_fn() if self.get_status_fn else None
            self._json({"running": run_id is not None, "run_id": run_id})
        elif self.path == "/detect-browsers":
            self._json(_detect_browsers())
        elif self.path == "/detect-python-versions":
            self._json(_detect_python_versions())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/create-venv":
            data = self._read_json()
            if not data:
                return
            python_exe = data.get("python_executable")
            venv_path = data.get("venv_path")
            if not python_exe or not venv_path:
                self._json({"error": "missing python_executable or venv_path"}, 400)
                return
            if not os.path.isfile(python_exe):
                self._json({"error": "python not found: {}".format(python_exe)}, 400)
                return
            try:
                proc = subprocess.run(
                    [python_exe, "-m", "venv", venv_path],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode != 0:
                    self._json({"error": "venv creation failed: {}".format(proc.stderr[:500])}, 500)
                    return
                venv_python = os.path.join(venv_path, "Scripts", "python.exe")
                if not os.path.isfile(venv_python):
                    self._json({"error": "venv created but python.exe not found"}, 500)
                    return
                self._json({"success": True, "venv_python": os.path.normpath(venv_python)})
            except subprocess.TimeoutExpired:
                self._json({"error": "venv creation timed out (120s)"}, 500)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif self.path == "/delete-venv":
            data = self._read_json()
            if not data:
                return
            venv_path = data.get("venv_path")
            if not venv_path:
                self._json({"error": "missing venv_path"}, 400)
                return
            if os.path.isdir(venv_path):
                try:
                    shutil.rmtree(venv_path)
                    self._json({"success": True})
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"success": True, "note": "directory not found"})
        else:
            self._json({"error": "not found"}, 404)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            return json.loads(body)
        except Exception:
            self._json({"error": "invalid json"}, 400)
            return None

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


def start_local_server(port, get_status_fn):
    AgentHandler.get_status_fn = get_status_fn
    server = HTTPServer(("127.0.0.1", port), AgentHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    return t
