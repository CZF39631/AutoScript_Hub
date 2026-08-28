import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from client.agent.local_server import AgentHandler


TOKEN = "test-agent-api-token-with-sufficient-entropy"


def _headers(**extra):
    return {"Authorization": "Bearer " + TOKEN, **extra}


def _server():
    AgentHandler.api_token = TOKEN
    server = HTTPServer(("127.0.0.1", 0), AgentHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_status_endpoint_reports_running_state_and_agent_version():
    AgentHandler.get_status_fn = lambda: None
    AgentHandler.get_version_fn = lambda: "0.9.1"
    server = _server()
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:{}/status".format(server.server_port), headers=_headers()
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())
        assert payload == {"running": False, "run_id": None, "version": "0.9.1"}
    finally:
        server.shutdown(); server.server_close()


def test_sensitive_endpoint_requires_token_and_rejects_foreign_origin():
    AgentHandler.get_connection_status_fn = lambda: {"online": True}
    server = _server()
    try:
        base = "http://127.0.0.1:{}/local/connection".format(server.server_port)
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(base, timeout=3)
        assert missing.value.code == 401

        request = urllib.request.Request(
            base,
            headers=_headers(Origin="https://evil.example"),
        )
        with pytest.raises(urllib.error.HTTPError) as foreign:
            urllib.request.urlopen(request, timeout=3)
        assert foreign.value.code == 403
        assert foreign.value.headers.get("Access-Control-Allow-Origin") is None
    finally:
        server.shutdown(); server.server_close()


def test_preflight_only_allows_desktop_ui_origin():
    server = _server()
    try:
        base = "http://127.0.0.1:{}/local/execute".format(server.server_port)
        request = urllib.request.Request(base, method="OPTIONS", headers={"Origin": "http://127.0.0.1:18081"})
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:18081"
            assert "Authorization" in response.headers["Access-Control-Allow-Headers"]

        request = urllib.request.Request(base, method="OPTIONS", headers={"Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as foreign:
            urllib.request.urlopen(request, timeout=3)
        assert foreign.value.code == 403
    finally:
        server.shutdown(); server.server_close()


def test_local_result_open_endpoint_calls_agent_callback():
    opened = []
    AgentHandler.open_result_fn = lambda path: opened.append(path) or {"success": True, "path": path}
    server = _server()
    try:
        body = json.dumps({"path": r"C:\results\report.xlsx"}).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:{}/local/results/open".format(server.server_port),
            data=body, headers=_headers(**{"Content-Type": "application/json"}), method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload == {"success": True, "path": r"C:\results\report.xlsx"}
        assert opened == [r"C:\results\report.xlsx"]
    finally:
        server.shutdown(); server.server_close()


def test_lifecycle_shutdown_endpoint_requests_drain_and_exit():
    requested = []
    AgentHandler.request_shutdown_fn = lambda: requested.append(True)
    server = _server()
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:{}/lifecycle/shutdown".format(server.server_port),
            data=b"{}", headers=_headers(), method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())
        assert response.status == 202
        assert payload == {"status": "draining"}
        assert requested == [True]
    finally:
        server.shutdown(); server.server_close()


def test_local_update_endpoints_expose_status_check_and_manual_install():
    AgentHandler.get_version_fn = lambda: "0.9.0"
    AgentHandler.get_update_status_fn = lambda: {"state": "verified", "version": "0.9.1"}
    AgentHandler.check_update_fn = lambda: {"state": "available", "version": "0.9.1"}
    AgentHandler.install_update_fn = lambda: {"state": "installing", "version": "0.9.1"}
    server = _server()
    try:
        base = "http://127.0.0.1:{}".format(server.server_port)
        with urllib.request.urlopen(urllib.request.Request(base + "/local/update", headers=_headers()), timeout=3) as response:
            assert json.loads(response.read())["state"] == "verified"
        for action, expected in (("check", "available"), ("install", "installing")):
            request = urllib.request.Request(
                base + "/local/update/" + action, data=b"{}",
                headers=_headers(**{"Content-Type": "application/json"}), method="POST",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                assert json.loads(response.read())["state"] == expected
    finally:
        server.shutdown(); server.server_close()


def test_local_runtime_endpoint_reports_the_managed_private_python():
    AgentHandler.get_runtime_info_fn = lambda: {"status": "ready", "managed": True, "version": "3.11.9"}
    server = _server()
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:{}/local/runtime".format(server.server_port), headers=_headers()
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())
        assert payload["managed"] is True
        assert payload["version"] == "3.11.9"
    finally:
        server.shutdown(); server.server_close()
