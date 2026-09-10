"""1.2.4 回归：版本锁定、执行互斥和离线历史续传。"""

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.agent import main as agent


def response(payload=None, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload or {})


@pytest.fixture(autouse=True)
def isolated_agent(monkeypatch, tmp_path):
    for name, value in {
        "_running_proc": None, "_running_info": {}, "_local_run_proc": None,
        "_local_run_info": {}, "_local_runs": {}, "_local_run_counter": 0, "_current_run_id": None,
        "_agent_id": 3, "_shutdown_when_idle": False,
        "_last_online_time": agent.time.time(),
        "_execution_start_lock": threading.Lock(),
        "_LOGS_DIR": str(tmp_path / "logs"),
        "_SCRIPTS_DIR": str(tmp_path / "scripts"),
        "_local_runs_file": str(tmp_path / "local_runs.json"),
    }.items():
        monkeypatch.setattr(agent, name, value)
    monkeypatch.setattr(agent, "_check_running_process", lambda: None)
    monkeypatch.setattr(agent, "_headers", lambda: {})
    monkeypatch.setattr(agent, "_notify_execution_result", lambda *a, **kw: None)
    # Any unexpected request fails instead of touching a real server.
    for method in ("get", "post", "patch"):
        monkeypatch.setattr(agent.requests, method, Mock(side_effect=AssertionError("unexpected network call")))


@pytest.mark.parametrize("cached", [True, False])
def test_online_run_uses_locked_version_not_new_market_version(monkeypatch, tmp_path, cached):
    run = {"id": 7, "script_id": 1, "script_version": 1, "params": "{}"}
    script_dir = tmp_path / "scripts" / "1" / "1"
    if cached:
        script_dir.mkdir(parents=True)
    seen = []

    def get(url, **kwargs):
        seen.append(url)
        if "status=pending" in url:
            return response([run])
        if url.endswith("/api/scripts/1"):
            return response({"name": "demo", "latest_version": 2})
        assert url.endswith("/api/scripts/1/download?version=1")
        return SimpleNamespace(status_code=200, content=b"fake-archive")

    monkeypatch.setattr(agent.requests, "get", get)
    monkeypatch.setattr(agent.requests, "post", lambda *a, **kw: response(run))
    monkeypatch.setattr(agent, "_install_downloaded_script", lambda payload, path: None)
    monkeypatch.setattr(agent, "parse_script_config", lambda path: {})
    start = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr(agent, "_start_script_subprocess", start)
    agent.poll_and_execute()
    assert start.call_args.args[0] == str(script_dir)
    assert any("download?version=1" in url for url in seen) is not cached


def test_missing_locked_version_fails_closed(monkeypatch):
    run = {"id": 7, "script_id": 1, "params": "{}"}
    monkeypatch.setattr(agent.requests, "get", Mock(side_effect=[response([run]), response({"latest_version": 2})]))
    monkeypatch.setattr(agent.requests, "post", lambda *a, **kw: response(run))
    failed = Mock()
    monkeypatch.setattr(agent, "_report_run_failure", failed)
    agent.poll_and_execute()
    assert "锁定脚本版本" in failed.call_args.args[1]
    assert agent._running_proc is None


def test_online_poll_cannot_start_while_local_process_exists(monkeypatch):
    monkeypatch.setattr(agent, "_local_run_proc", object())
    agent.poll_and_execute()
    agent.requests.get.assert_not_called()


def test_start_gate_rejects_both_entrypoints_during_preparation():
    with agent._execution_start_lock:
        assert "error" in agent.start_local_run({"script_id": 1})
        agent.poll_and_execute()
    agent.requests.get.assert_not_called()


def test_local_request_during_online_preparation_cannot_start(monkeypatch):
    attempted = []

    def get(url, **kwargs):
        if "status=pending" in url:
            attempted.append(agent.start_local_run({"script_id": 1}))
            return response([])
        raise AssertionError(url)

    monkeypatch.setattr(agent.requests, "get", get)
    agent.poll_and_execute()
    assert attempted == [{"error": "another task is running"}]
    assert not agent._execution_start_lock.locked()


def test_processes_have_distinct_parameter_files(monkeypatch, tmp_path):
    commands = []

    def popen(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(pid=len(commands))

    monkeypatch.setattr(agent.subprocess, "Popen", popen)
    a = agent._start_script_subprocess(str(tmp_path), {"value": 1}, str(tmp_path / "a.log"), 10)
    b = agent._start_script_subprocess(str(tmp_path), {"value": 2}, str(tmp_path / "b.log"), 10)
    try:
        assert a._params_file != b._params_file
        for proc, value, command in ((a, 1, commands[0]), (b, 2, commands[1])):
            with open(proc._params_file, encoding="utf-8") as stream:
                assert json.load(stream) == {"value": value}
            assert command[-1] == proc._params_file
    finally:
        a._log_file.close()
        b._log_file.close()


def test_failed_spawn_cleans_its_parameter_file(monkeypatch, tmp_path):
    monkeypatch.setattr(agent.subprocess, "Popen", Mock(side_effect=OSError("spawn failed")))
    with pytest.raises(OSError, match="spawn failed"):
        agent._start_script_subprocess(str(tmp_path), {}, str(tmp_path / "a.log"), 10)
    assert not list(tmp_path.glob("params-*.json"))


@pytest.mark.parametrize("failure", ["log-open", "serialization"])
def test_pre_spawn_failure_cleans_parameter_file(tmp_path, failure):
    log_path = tmp_path / "a.log"
    params = {}
    if failure == "log-open":
        log_path.mkdir()
    else:
        params = {"invalid": object()}
    with pytest.raises((OSError, TypeError)):
        agent._start_script_subprocess(str(tmp_path), params, str(log_path), 10)
    assert not list(tmp_path.glob("params-*.json"))


def local_record():
    return {"script_id": 1, "script_version": 1, "status": "success", "params": {},
            "log_path": "fake.log", "synced": False, "backend_run_id": None}


@pytest.mark.parametrize("failure", ["log", "status", "claim-response"])
def test_sync_retries_same_backend_record_after_failure(monkeypatch, failure):
    rec = local_record()
    agent._local_runs["L1"] = rec
    remote = {"id": 7, "agent_id": None, "status": "pending"}
    calls = []
    first = [True]

    def post(url, **kwargs):
        calls.append(url)
        if url.endswith("/execute"):
            assert len([x for x in calls if x.endswith("/execute")]) == 1
            return response({"id": 7})
        assert url.endswith("/7/claim")
        assert rec["backend_run_id"] == 7
        with open(agent._local_runs_file, encoding="utf-8") as stream:
            assert json.load(stream)["L1"]["backend_run_id"] == 7
        remote.update(status="running", agent_id=3)
        if failure == "claim-response" and first[0]:
            first[0] = False
            raise agent.requests.Timeout("lost claim response")
        return response(remote)

    def patch(url, json, **kwargs):
        assert url.endswith("/7/status")
        if failure == "status" and first[0]:
            first[0] = False
            return response(status=503)
        remote["status"] = json["status"]
        return response()

    upload = Mock(side_effect=[False, True] if failure == "log" else None, return_value=True)
    monkeypatch.setattr(agent.requests, "post", post)
    monkeypatch.setattr(agent.requests, "patch", patch)
    monkeypatch.setattr(agent.requests, "get", lambda *a, **kw: response(remote.copy()))
    monkeypatch.setattr(agent, "_upload_log_delta", upload)
    agent._sync_local_runs_to_backend()
    assert rec["synced"] is False
    assert rec["backend_run_id"] == 7
    if failure == "log":
        assert remote["status"] == "success"  # Failed log upload must not hold the slot.
    # Simulate restart by loading only the persisted data.
    agent._load_local_runs()
    agent._sync_local_runs_to_backend()
    assert agent._local_runs["L1"]["synced"] is True
    assert remote["status"] == "success"
    assert len([url for url in calls if url.endswith("/execute")]) == 1
    assert len([url for url in calls if url.endswith("/claim")]) == 1


def test_sync_does_not_overwrite_another_agents_run(monkeypatch):
    agent._local_runs["L1"] = dict(local_record(), backend_run_id=7)
    monkeypatch.setattr(agent.requests, "get", lambda *a, **kw: response({"id": 7, "agent_id": 99, "status": "running"}))
    agent._sync_local_runs_to_backend()
    agent.requests.post.assert_not_called()
    agent.requests.patch.assert_not_called()


def test_sync_finishes_cancelled_unclaimed_import_without_changing_status(monkeypatch):
    agent._local_runs["L1"] = dict(local_record(), backend_run_id=7)
    monkeypatch.setattr(agent.requests, "get", lambda *a, **kw: response({"id": 7, "agent_id": None, "status": "cancelled"}))
    monkeypatch.setattr(agent, "_upload_log_delta", lambda *a, **kw: True)
    agent._sync_local_runs_to_backend()
    assert agent._local_runs["L1"]["synced"] is True
    agent.requests.post.assert_not_called()
    agent.requests.patch.assert_not_called()


def test_poll_never_executes_pending_local_history_import(monkeypatch):
    agent._local_runs["L1"] = dict(local_record(), backend_run_id=7)
    monkeypatch.setattr(agent.requests, "get", lambda *a, **kw: response([{"id": 7, "script_id": 1}]))
    agent.poll_and_execute()
    agent.requests.post.assert_not_called()


def test_log_exception_still_reports_terminal_status(monkeypatch):
    agent._local_runs["L1"] = dict(local_record(), backend_run_id=7)
    monkeypatch.setattr(agent.requests, "get", lambda *a, **kw: response({"id": 7, "agent_id": 3, "status": "running"}))
    monkeypatch.setattr(agent, "_upload_log_delta", Mock(side_effect=OSError("log unreadable")))
    patch = Mock(return_value=response())
    monkeypatch.setattr(agent.requests, "patch", patch)
    agent._sync_local_runs_to_backend()
    assert patch.call_args.kwargs["json"]["status"] == "success"
    assert not agent._local_runs["L1"]["synced"]
