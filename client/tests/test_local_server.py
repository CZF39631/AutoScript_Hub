import json
import threading
import urllib.request
from http.server import HTTPServer

from client.agent.local_server import AgentHandler


def test_status_endpoint_reports_running_state_and_agent_version():
    AgentHandler.get_status_fn = lambda: None
    AgentHandler.get_version_fn = lambda: "0.9.1"
    server = HTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:{}/status".format(server.server_port), timeout=3
        ) as response:
            payload = json.loads(response.read())
        assert payload == {"running": False, "run_id": None, "version": "0.9.1"}
    finally:
        server.shutdown()
        server.server_close()


def test_local_result_open_endpoint_calls_agent_callback():
    opened = []
    AgentHandler.open_result_fn = lambda path: opened.append(path) or {
        "success": True,
        "path": path,
    }
    server = HTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        body = json.dumps({"path": r"C:\results\report.xlsx"}).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:{}/local/results/open".format(server.server_port),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload == {"success": True, "path": r"C:\results\report.xlsx"}
        assert opened == [r"C:\results\report.xlsx"]
    finally:
        server.shutdown()
        server.server_close()


def test_local_update_endpoints_expose_status_check_and_manual_install():
    AgentHandler.get_update_status_fn = lambda: {"state": "verified", "version": "0.9.1"}
    AgentHandler.check_update_fn = lambda: {"state": "verified", "version": "0.9.1"}
    AgentHandler.install_update_fn = lambda: {"state": "installing", "version": "0.9.1"}
    server = HTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = "http://127.0.0.1:{}".format(server.server_port)
        with urllib.request.urlopen(base + "/local/update", timeout=3) as response:
            assert json.loads(response.read()) == {"state": "verified", "version": "0.9.1"}
        for action, expected in (("check", "verified"), ("install", "installing")):
            request = urllib.request.Request(
                base + "/local/update/" + action,
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                assert json.loads(response.read())["state"] == expected
    finally:
        server.shutdown()
        server.server_close()


def test_local_runtime_endpoint_reports_the_managed_private_python():
    AgentHandler.get_runtime_info_fn = lambda: {
        "status": "ready",
        "managed": True,
        "version": "3.11.9",
        "path": r"C:\AutoScript Hub\runtime\python\python.exe",
    }
    server = HTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:{}/local/runtime".format(server.server_port), timeout=3
        ) as response:
            payload = json.loads(response.read())
        assert payload["managed"] is True
        assert payload["version"] == "3.11.9"
    finally:
        server.shutdown()
        server.server_close()
