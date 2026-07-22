import io
import os
import zipfile

import pytest

from client.agent import main as agent


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


def test_upload_log_delta_sends_only_new_utf8_bytes(tmp_path, monkeypatch):
    log_path = tmp_path / "run.log"
    log_path.write_bytes("开始\n".encode("utf-8"))
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(json.copy())
        return _Response(200, {"offset": json["offset"] + len(json["content"].encode("utf-8"))})

    monkeypatch.setattr(agent.requests, "post", fake_post)
    agent._log_upload_offsets.clear()

    assert agent._upload_log_delta(7, str(log_path)) is True
    with log_path.open("ab") as f:
        f.write(b"done\n")
    assert agent._upload_log_delta(7, str(log_path), force=True) is True
    assert agent._upload_log_delta(7, str(log_path)) is True

    assert calls == [
        {"offset": 0, "content": "开始\n"},
        {"offset": len("开始\n".encode("utf-8")), "content": "done\n"},
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
        lambda run_id, path, force=False: uploaded.append((run_id, path, force)) or True,
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

    assert uploaded == [(88, r"C:\logs\local_L1.log", True)]
    assert agent._local_runs["L1"]["synced"] is True


def test_failed_final_log_upload_is_retried(monkeypatch):
    outcomes = iter([False, True])
    monkeypatch.setattr(
        agent,
        "_upload_log_delta",
        lambda run_id, path, force=False: next(outcomes),
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
