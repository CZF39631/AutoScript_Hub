"""pywebview UI — 本地托管 React 前端，/api/* 代理到后端"""
import os
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler

import webview

from client.ui.config_manager import load_config, is_setup_complete

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LOCAL_PORT = 18081


class LocalUIHandler(SimpleHTTPRequestHandler):
    """Serve frontend static files + proxy /api/* to the backend."""

    backend_url = "http://127.0.0.1:8000"

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy("GET")
        return self._serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy("POST")
        self.send_error(405)

    def do_PUT(self):
        if self.path.startswith("/api/"):
            return self._proxy("PUT")
        self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            return self._proxy("DELETE")
        self.send_error(405)

    def do_PATCH(self):
        if self.path.startswith("/api/"):
            return self._proxy("PATCH")
        self.send_error(405)

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            return self._proxy("OPTIONS")
        self.send_error(405)

    def _serve_static(self):
        """Serve static files, fallback to index.html for SPA routes."""
        path = self.path.split("?")[0].split("#")[0]
        if path == "/":
            path = "/index.html"

        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))
        file_path = os.path.normpath(file_path)

        if not file_path.startswith(os.path.normpath(STATIC_DIR)):
            self.send_error(403)
            return

        if not os.path.isfile(file_path):
            path = "/index.html"
            file_path = os.path.join(STATIC_DIR, "index.html")

        # Inject backend URL into index.html for SSE connections
        if path == "/index.html" or file_path.endswith("index.html"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                inject = '<script>window._BACKEND_URL="{}"</script>\n'.format(self.backend_url)
                content = content.replace("</head>", inject + "</head>")
                data = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            except OSError:
                pass

        # Regular static file serving
        self.directory = STATIC_DIR
        self.path = "/" + os.path.relpath(file_path, STATIC_DIR).replace("\\", "/")
        return SimpleHTTPRequestHandler.do_GET(self)

    def _proxy(self, method):
        """Proxy request to the backend server."""
        target_url = self.backend_url + self.path
        body = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            try:
                body = self.rfile.read(int(content_length))
            except (ValueError, OSError):
                body = None

        # Forward relevant headers (skip host/connection)
        headers = {}
        for key, val in self.headers.items():
            if key.lower() not in ("host", "connection", "transfer-encoding", "content-length"):
                headers[key] = val

        req = urllib.request.Request(
            target_url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                # Forward response headers
                for key, val in resp.headers.items():
                    if key.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                        self.send_header(key, val)
                # Recalculate content-length
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            data = e.read()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except urllib.error.URLError as e:
            self.send_error(502, "Backend unreachable: {}".format(e.reason))

    def log_message(self, format, *args):
        pass


class Api:
    """JS bridge for pywebview2 native dialogs."""

    def openFileDialog(self, file_types=("All files (*.*)",)):
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=file_types
        )
        return result[0] if result else None

    def openFolderDialog(self):
        result = webview.windows[0].create_file_dialog(
            webview.FOLDER_DIALOG
        )
        return result[0] if result else None


def start_local_server(backend_url):
    """Start the local HTTP server that serves frontend + proxies API."""
    LocalUIHandler.backend_url = backend_url
    server = HTTPServer(("127.0.0.1", LOCAL_PORT), LocalUIHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def start_ui():
    config = load_config()
    backend_url = config.get("server_url", "http://127.0.0.1:8000")

    # Show wizard on first run
    if not is_setup_complete():
        from client.ui.wizard import run_wizard
        run_wizard()
        # Reload config after wizard
        config = load_config()
        backend_url = config.get("server_url", "http://127.0.0.1:8000")

    # Start local server for frontend + API proxy
    start_local_server(backend_url)

    frontend_url = "http://127.0.0.1:{}/".format(LOCAL_PORT)

    api = Api()
    window = webview.create_window(
        "AutoScript Hub",
        frontend_url,
        js_api=api,
        width=1200,
        height=800,
        min_size=(800, 600),
    )
    webview.start()


if __name__ == "__main__":
    start_ui()
