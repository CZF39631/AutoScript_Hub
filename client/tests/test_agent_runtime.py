import io
import os
import time
import zipfile

import pytest

from client.agent import main as agent
from client.agent.executor import execute_script


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for name, content in entries.items():
            bundle.writestr(name, content)
    return stream.getvalue()


def test_agent_uses_fast_polling_while_a_script_is_running():
    original_running = agent._running_proc
    original_local = agent._local_run_proc
    try:
        agent._running_proc = None
        agent._local_run_proc = None
        assert agent._next_poll_interval() == agent.POLL_INTERVAL
        agent._running_proc = object()
        assert agent._next_poll_interval() == agent.LIVE_POLL_INTERVAL
    finally:
        agent._running_proc = original_running
        agent._local_run_proc = original_local


def test_shutdown_request_enters_drain_mode_and_rejects_new_local_runs():
    agent._shutdown_when_idle = False
    try:
        agent.request_shutdown_when_idle()
        assert agent._shutdown_when_idle is True
        assert agent.start_local_run({"script_id": 1}) == {
            "error": "Agent 正在退出，不能启动新任务"
        }
    finally:
        agent._shutdown_when_idle = False


def test_connected_run_completion_reports_status_and_shows_notification(monkeypatch):
    reports = []
    notifications = []
    monkeypatch.setattr(agent, "_check_running_process", lambda: {
        "status": "success",
        "error": None,
        "result": None,
        "run_id": 21,
        "log_path": None,
        "script_dir": None,
        "script_name": "通知测试脚本",
    })
    monkeypatch.setattr(agent, "_report_run_status", lambda run_id, update: reports.append((run_id, update)))
    monkeypatch.setattr(agent, "_notify_execution_result", lambda name, status, error=None: notifications.append((name, status, error)))

    agent.poll_and_execute()

    assert reports == [(21, {"status": "success"})]
    assert notifications == [("通知测试脚本", "success", None)]


def test_poll_does_not_claim_new_backend_work_while_draining(monkeypatch):
    agent._shutdown_when_idle = True
    agent._running_proc = None
    agent._running_info = {}
    monkeypatch.setattr(agent, "_check_running_process", lambda: None)
    monkeypatch.setattr(
        agent.requests,
        "get",
        lambda *args, **kwargs: pytest.fail("排空期间不应领取新任务"),
    )
    try:
        agent.poll_and_execute()
    finally:
        agent._shutdown_when_idle = False


def test_script_subprocess_streams_stdout_before_process_exit(tmp_path):
    script_dir = tmp_path / "script"
    script_dir.mkdir()
    (script_dir / "main.py").write_text(
        "import time\ndef main():\n    print('live-line')\n    time.sleep(3)\n",
        encoding="utf-8",
    )
    log_path = tmp_path / "logs" / "live.log"
    proc = agent._start_script_subprocess(
        str(script_dir), {}, str(log_path), timeout=10, python_executable=os.sys.executable
    )
    try:
        deadline = time.time() + 2
        content = b""
        while time.time() < deadline:
            content = log_path.read_bytes() if log_path.exists() else b""
            if b"live-line" in content:
                break
            time.sleep(0.05)
        assert b"live-line" in content
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=5)
        proc._log_file.close()


def test_downloaded_script_is_safely_extracted_and_legacy_root_is_normalized(tmp_path):
    target = tmp_path / "scripts" / "4" / "1"
    payload = _zip_bytes({"old-package/main.py": "def main(): return None"})

    agent._install_downloaded_script(payload, target)

    assert (target / "main.py").is_file()
    assert not (target / "old-package").exists()


def test_downloaded_script_rejects_archive_traversal_without_partial_install(tmp_path):
    target = tmp_path / "scripts" / "4" / "1"
    payload = _zip_bytes({"../outside.py": "bad", "main.py": "def main(): return None"})

    with pytest.raises(ValueError, match="不安全路径"):
        agent._install_downloaded_script(payload, target)

    assert not target.exists()
    assert not (tmp_path / "scripts" / "4" / "outside.py").exists()


def test_script_result_parser_accepts_literals_without_executing_code(tmp_path):
    marker = tmp_path / "executed"
    malicious = "__import__('pathlib').Path({!r}).write_text('bad')".format(str(marker))

    assert agent._parse_result_literal("['report.xlsx']") == ["report.xlsx"]
    assert agent._parse_result_literal(malicious) == malicious
    assert not marker.exists()


def test_executor_result_marker_starts_on_own_line_after_unterminated_stdout(tmp_path):
    script_dir = tmp_path / "script"
    script_dir.mkdir()
    (script_dir / "main.py").write_text(
        "import sys\n\n"
        "def main():\n"
        "    sys.stdout.write('progress')\n"
        "    return ['report.xlsx']\n",
        encoding="utf-8",
    )
    log_path = tmp_path / "run.log"

    result = execute_script(str(script_dir), {}, str(log_path))

    assert result["status"] == "success"
    assert result["result"] == ["report.xlsx"]
    assert "\n__RESULT__:['report.xlsx']\n" in log_path.read_text(encoding="utf-8")


def test_upload_log_delta_sends_only_new_utf8_bytes(tmp_path, monkeypatch):
    log_path = tmp_path / "run.log"
    log_path.write_bytes("开始\n".encode("utf-8"))
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(json.copy())
        return _Response(200, {"offset": json["offset"] + len(json["content"].encode("utf-8"))})

    monkeypatch.setattr(agent.requests, "post", fake_post)
    agent._log_upload_offsets.clear()

    assert agent._upload_log_delta(7, str(log_path), agent_id=11) is True
    with log_path.open("ab") as f:
        f.write(b"done\n")
    assert agent._upload_log_delta(7, str(log_path), force=True, agent_id=11) is True
    assert agent._upload_log_delta(7, str(log_path), agent_id=11) is True

    assert calls == [
        {"offset": 0, "content": "开始\n", "agent_id": 11},
        {"offset": len("开始\n".encode("utf-8")), "content": "done\n", "agent_id": 11},
    ]


def test_upload_log_delta_uses_server_offset_after_conflict(tmp_path, monkeypatch):
    log_path = tmp_path / "run.log"
    log_path.write_text("complete", encoding="utf-8")
    responses = [
        _Response(409, {"detail": {"offset": 0}}),
        _Response(200, {"offset": len(b"complete")}),
    ]
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(json.copy())
        return responses.pop(0)

    monkeypatch.setattr(agent.requests, "post", fake_post)
    agent._log_upload_offsets.clear()
    agent._log_upload_offsets[9] = 4

    assert agent._upload_log_delta(9, str(log_path)) is False
    assert agent._upload_log_delta(9, str(log_path)) is True
    assert calls[0]["offset"] == 4
    assert calls[1] == {"offset": 0, "content": "complete"}


def test_poll_skips_script_download_when_another_agent_claims_first(monkeypatch):
    requests_seen = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        requests_seen.append(("get", url))
        return Response(200, [{"id": 37, "script_id": 1}])

    def fake_post(url, json, **kwargs):
        requests_seen.append(("post", url, json))
        return Response(409, {"detail": "任务已被领取"})

    monkeypatch.setattr(agent.requests, "get", fake_get)
    monkeypatch.setattr(agent.requests, "post", fake_post)
    monkeypatch.setattr(agent, "_check_running_process", lambda: None)
    agent._running_proc = None
    agent._running_info = {}
    agent._current_run_id = None
    agent._agent_id = 11

    agent.poll_and_execute()

    assert requests_seen == [
        ("get", "{}/api/runs?status=pending&limit=1&mine_only=true".format(agent.BACKEND_URL)),
        ("post", "{}/api/runs/37/claim".format(agent.BACKEND_URL), {"agent_id": 11}),
    ]
    assert agent._current_run_id is None


def test_poll_claims_before_loading_or_starting_a_script(monkeypatch, tmp_path):
    requests_seen = []
    started = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        requests_seen.append(("get", url))
        if "status=pending" in url:
            return Response(200, [{"id": 38, "script_id": 1}])
        if url.endswith("/api/scripts/1"):
            return Response(200, {"latest_version": 1})
        raise AssertionError("unexpected GET: {}".format(url))

    def fake_post(url, json, **kwargs):
        requests_seen.append(("post", url, json))
        return Response(200, {"id": 38, "script_id": 1, "params": "{}"})

    monkeypatch.setattr(agent.requests, "get", fake_get)
    monkeypatch.setattr(agent.requests, "post", fake_post)
    monkeypatch.setattr(agent, "_check_running_process", lambda: None)
    monkeypatch.setattr(agent.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(agent, "parse_script_config", lambda path: {})
    monkeypatch.setattr(agent, "_start_script_subprocess", lambda *args, **kwargs: started.append(args) or object())
    monkeypatch.setattr(agent, "_LOGS_DIR", str(tmp_path))
    agent._running_proc = None
    agent._running_info = {}
    agent._current_run_id = None
    agent._agent_id = 12

    agent.poll_and_execute()

    assert requests_seen[:2] == [
        ("get", "{}/api/runs?status=pending&limit=1&mine_only=true".format(agent.BACKEND_URL)),
        ("post", "{}/api/runs/38/claim".format(agent.BACKEND_URL), {"agent_id": 12}),
    ]
    assert requests_seen[2] == ("get", "{}/api/scripts/1".format(agent.BACKEND_URL))
    assert len(started) == 1


def test_poll_fails_a_claimed_run_when_script_metadata_cannot_be_loaded(monkeypatch):
    status_updates = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "status=pending" in url:
            return Response(200, [{"id": 39, "script_id": 1}])
        if url.endswith("/api/scripts/1"):
            return Response(404, {})
        raise AssertionError("unexpected GET: {}".format(url))

    def fake_post(url, json, **kwargs):
        assert url.endswith("/api/runs/39/claim")
        return Response(200, {"id": 39, "script_id": 1, "params": "{}"})

    def fake_patch(url, json, **kwargs):
        status_updates.append((url, json))
        return Response(200, {})

    monkeypatch.setattr(agent.requests, "get", fake_get)
    monkeypatch.setattr(agent.requests, "post", fake_post)
    monkeypatch.setattr(agent.requests, "patch", fake_patch)
    monkeypatch.setattr(agent, "_check_running_process", lambda: None)
    agent._running_proc = None
    agent._running_info = {}
    agent._current_run_id = None
    agent._agent_id = 13

    agent.poll_and_execute()

    assert status_updates == [
        (
            "{}/api/runs/39/status".format(agent.BACKEND_URL),
            {"status": "failed", "error_msg": "Failed to load script metadata", "agent_id": 13},
        )
    ]
    assert agent._current_run_id is None


def test_normalize_result_files_keeps_metadata_only(tmp_path):
    existing = tmp_path / "report.xlsx"
    existing.write_bytes(b"spreadsheet-content")
    missing = tmp_path / "missing.csv"

    result = agent._normalize_result_files([str(existing), str(missing)])

    assert result == [
        {
            "name": "report.xlsx",
            "path": os.path.abspath(existing),
            "exists": True,
            "size": len(b"spreadsheet-content"),
        },
        {
            "name": "missing.csv",
            "path": os.path.abspath(missing),
            "exists": False,
            "size": None,
        },
    ]


def test_normalize_result_files_resolves_relative_paths_from_script_directory(tmp_path):
    output = tmp_path / "output.csv"
    output.write_text("row", encoding="utf-8")

    result = agent._normalize_result_files("output.csv", base_dir=str(tmp_path))

    assert result[0]["path"] == str(output)
    assert result[0]["exists"] is True


def test_open_local_result_uses_desktop_opener(tmp_path, monkeypatch):
    result_file = tmp_path / "result.txt"
    result_file.write_text("ok", encoding="utf-8")
    opened = []
    monkeypatch.setattr(agent.os, "startfile", lambda path: opened.append(path))

    response = agent.open_local_result(str(result_file))

    assert response == {"success": True, "path": os.path.abspath(result_file)}
    assert opened == [os.path.abspath(result_file)]


def test_open_local_result_rejects_missing_file(tmp_path):
    response = agent.open_local_result(str(tmp_path / "missing.txt"))
    assert response["success"] is False
    assert "不存在" in response["error"]


def test_initialize_agent_runtime_starts_local_api_before_authentication(monkeypatch):
    events = []

    class FakeThread:
        daemon = False

        def start(self):
            events.append("local-api-started")

    monkeypatch.setattr(agent, "_load_pending_reports", lambda: events.append("pending-loaded"))
    monkeypatch.setattr(agent, "_load_local_runs", lambda: events.append("runs-loaded"))
    monkeypatch.setattr(agent, "start_local_server", lambda *args, **kwargs: FakeThread())

    agent.initialize_agent_runtime()

    assert events == ["pending-loaded", "runs-loaded", "local-api-started"]


def test_agent_iteration_stays_alive_offline_and_recovers_authentication(monkeypatch):
    events = []
    attempts = iter([False, True])

    def fake_authenticate(username, password):
        success = next(attempts)
        if success:
            agent._token = "token"
        events.append("auth-ok" if success else "auth-failed")
        return success

    monkeypatch.setattr(agent, "authenticate", fake_authenticate)
    monkeypatch.setattr(agent, "register_agent", lambda: events.append("registered") or 3)
    monkeypatch.setattr(agent, "_flush_pending_reports", lambda: events.append("reports"))
    monkeypatch.setattr(agent, "_check_local_runs", lambda: events.append("local-runs"))
    monkeypatch.setattr(agent, "poll_and_execute", lambda: events.append("poll"))
    monkeypatch.setattr(agent, "send_heartbeat", lambda: events.append("heartbeat") or True)
    monkeypatch.setattr(agent, "_sync_local_runs_to_backend", lambda: events.append("sync"))
    monkeypatch.setattr(agent, "_check_offline_notification", lambda: events.append("notify"))
    monkeypatch.setattr(agent, "_check_and_stage_update", lambda: {"state": "idle"})
    monkeypatch.setattr(agent, "_get_update_status", lambda: {"state": "idle"})
    monkeypatch.setattr(agent, "_sync_script_authorizations", lambda: False)
    agent._token = None
    agent._agent_id = None
    agent._last_update_check_time = 0

    assert agent.agent_iteration("operator", "secret") is False
    assert "local-runs" in events
    assert "poll" not in events

    assert agent.agent_iteration("operator", "secret") is True
    assert events[-6:] == ["reports", "local-runs", "poll", "heartbeat", "sync", "notify"]
    assert "registered" in events


def test_authenticated_agent_checks_updates_on_start_and_every_six_hours(monkeypatch):
    checks = []
    clock = [1000.0]
    agent._token = "token"
    agent._last_update_check_time = 0
    monkeypatch.setattr(agent.time, "time", lambda: clock[0])
    monkeypatch.setattr(agent, "_check_and_stage_update", lambda: checks.append(clock[0]) or {"state": "idle"})
    monkeypatch.setattr(agent, "_sync_client_settings", lambda: False)
    monkeypatch.setattr(agent, "_sync_script_authorizations", lambda: False)
    monkeypatch.setattr(agent, "_flush_pending_reports", lambda: None)
    monkeypatch.setattr(agent, "_flush_pending_log_uploads", lambda: None)
    monkeypatch.setattr(agent, "_check_local_runs", lambda: None)
    monkeypatch.setattr(agent, "poll_and_execute", lambda: None)
    monkeypatch.setattr(agent, "send_heartbeat", lambda: True)
    monkeypatch.setattr(agent, "_sync_local_runs_to_backend", lambda: None)
    monkeypatch.setattr(agent, "_check_offline_notification", lambda: None)
    monkeypatch.setattr(agent, "_get_update_status", lambda: {"state": "idle"})

    assert agent.agent_iteration("operator", "secret") is True
    clock[0] += agent.UPDATE_CHECK_INTERVAL_SEC - 1
    assert agent.agent_iteration("operator", "secret") is True
    clock[0] += 1
    assert agent.agent_iteration("operator", "secret") is True

    assert checks == [1000.0, 1000.0 + agent.UPDATE_CHECK_INTERVAL_SEC]


def test_scheduled_check_does_not_install_when_update_waits_for_idle(monkeypatch):
    checks = []
    installs = []
    agent._token = "token"
    agent._last_update_check_time = 1000.0
    monkeypatch.setattr(agent.time, "time", lambda: 1000.0)
    monkeypatch.setattr(agent, "_check_and_stage_update", lambda: checks.append(True) or {"state": "waiting-for-idle"})
    monkeypatch.setattr(agent, "_install_staged_update", lambda: installs.append(True))
    monkeypatch.setattr(agent, "_get_update_status", lambda: {"state": "waiting-for-idle"})
    monkeypatch.setattr(agent, "_sync_client_settings", lambda: False)
    monkeypatch.setattr(agent, "_sync_script_authorizations", lambda: False)
    monkeypatch.setattr(agent, "_flush_pending_reports", lambda: None)
    monkeypatch.setattr(agent, "_flush_pending_log_uploads", lambda: None)
    monkeypatch.setattr(agent, "_check_local_runs", lambda: None)
    monkeypatch.setattr(agent, "poll_and_execute", lambda: None)
    monkeypatch.setattr(agent, "send_heartbeat", lambda: True)
    monkeypatch.setattr(agent, "_sync_local_runs_to_backend", lambda: None)
    monkeypatch.setattr(agent, "_check_offline_notification", lambda: None)

    assert agent.agent_iteration("operator", "secret") is True
    assert installs == []


def test_sync_client_settings_merges_allowed_fields_and_preserves_identity(tmp_path, monkeypatch):
    config_path = tmp_path / "client_config.json"
    config_path.write_text(
        '{"username":"operator","password":"secret","version":"1.2.3","output_dir":"old"}',
        encoding="utf-8",
    )

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "output_dir": r"D:\results",
                "browser_debug_port": 9333,
                "username": "must-not-overwrite",
            }

    monkeypatch.setattr(agent.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(agent, "_CLIENT_CONFIG_PATH", str(config_path))

    assert agent._sync_client_settings() is True
    saved = __import__("json").loads(config_path.read_text(encoding="utf-8"))
    assert saved == {
        "username": "operator",
        "password": "secret",
        "version": "1.2.3",
        "output_dir": r"D:\results",
        "browser_debug_port": 9333,
    }


def test_sync_local_run_uploads_final_log_before_marking_synced(monkeypatch):
    uploaded = []

    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    monkeypatch.setattr(agent.requests, "post", lambda *args, **kwargs: Response(200, {"id": 88}))
    monkeypatch.setattr(agent.requests, "patch", lambda *args, **kwargs: Response(200))
    monkeypatch.setattr(
        agent,
        "_upload_log_delta",
        lambda run_id, path, force=False, agent_id=None: uploaded.append((run_id, path, force, agent_id)) or True,
    )
    monkeypatch.setattr(agent, "_save_local_runs", lambda: None)
    agent._agent_id = 3
    agent._last_online_time = agent.time.time()
    agent._local_runs = {
        "L1": {
            "local_run_id": "L1",
            "script_id": 4,
            "params": {},
            "status": "success",
            "log_path": r"C:\logs\local_L1.log",
            "result_files": None,
            "synced": False,
        }
    }

    agent._sync_local_runs_to_backend()

    assert uploaded == [(88, r"C:\logs\local_L1.log", True, 3)]
    assert agent._local_runs["L1"]["synced"] is True


def test_failed_final_log_upload_is_retried(monkeypatch):
    outcomes = iter([False, True])
    monkeypatch.setattr(
        agent,
        "_upload_log_delta",
        lambda run_id, path, force=False, agent_id=None: next(outcomes),
    )
    monkeypatch.setattr(agent, "_save_pending_log_uploads", lambda: None)
    agent._pending_log_uploads.clear()

    assert agent._finish_log_upload(15, r"C:\logs\15.log") is False
    assert agent._pending_log_uploads == {15: r"C:\logs\15.log"}

    agent._flush_pending_log_uploads()
    assert agent._pending_log_uploads == {}


def test_empty_pending_log_queue_removes_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / ".pending_log_uploads.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(agent, "PENDING_LOG_UPLOADS_FILE", str(state_file))
    agent._pending_log_uploads.clear()

    agent._save_pending_log_uploads()

    assert not state_file.exists()


def test_heartbeat_401_clears_token_for_automatic_reauthentication(monkeypatch):
    class Response:
        status_code = 401

    monkeypatch.setattr(agent.requests, "post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(agent, "_detect_machine_info", lambda: ("pc", "127.0.0.1"))
    agent._token = "expired"
    agent._agent_id = 5

    assert agent.send_heartbeat() is False
    assert agent._token is None
