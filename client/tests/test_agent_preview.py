"""迁移后的回归：锁定版本、准备门禁、参数文件与幂等终态导入。"""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from client.tests.test_task_agent import agent, cache  # isolated ClientPaths fixture


def legacy(agent, monkeypatch, run):
    monkeypatch.setattr(agent, '_agent_id', 3)
    monkeypatch.setattr(agent._task_device, 'register', Mock(side_effect=RuntimeError('old server')))
    calls = []
    def request(method, route, body=None, extra_headers=None):
        calls.append((method, route, body))
        if 'status=pending' in route:
            return [run]
        if route.endswith('/claim'):
            return run
        return {}
    monkeypatch.setattr(agent, '_task_request', request)
    return calls


@pytest.mark.parametrize('cached', [True, False])
def test_online_run_uses_locked_version_not_new_market_version(agent, monkeypatch, cached):
    cache(agent, monkeypatch)
    run = {'id': 7, 'script_id': 1, 'script_version': 1, 'params': {'choice': 'old'}}
    calls = legacy(agent, monkeypatch, run)
    directory = agent._CLIENT_PATHS.scripts_dir / '1' / '1'
    downloaded = []
    if not cached:
        (directory / 'main.py').unlink()
        directory.rmdir()
        monkeypatch.setattr(agent.requests, 'get', lambda url, **kw: downloaded.append(url) or
                            SimpleNamespace(content=b'mock', raise_for_status=lambda: None))
        def install(payload, path):
            directory.mkdir()
            (directory / 'main.py').write_text('# mock')
        monkeypatch.setattr(agent, '_install_downloaded_script', install)
    monkeypatch.setattr(agent, 'prepare_environment', lambda *a, **kw: 'python')
    started = []
    def spawn(item, python):
        started.append(item['script_dir'])
        raise RuntimeError('mock ends before spawning')
    monkeypatch.setattr(agent._controller, 'spawn', spawn)
    agent.poll_and_execute()
    agent._controller.worker.join(2)
    assert started == [str(directory)]
    assert calls[1][1].endswith('/claim')
    assert bool(downloaded) is not cached
    assert all('version=1' in url for url in downloaded)


def test_missing_locked_version_fails_closed(agent, monkeypatch):
    legacy(agent, monkeypatch, {'id': 7, 'script_id': 1, 'params': {}})
    agent.poll_and_execute()
    agent._controller.worker.join(2)
    event = agent._task_store.events()[0]
    assert event['state'] == 'failed'
    assert 'script_version' in event['error_msg']


def test_online_poll_cannot_start_while_local_process_exists(agent, monkeypatch):
    monkeypatch.setattr(agent, '_local_run_proc', object())
    agent.poll_and_execute()  # fixture denies every network request


def test_start_gate_rejects_both_entrypoints_during_preparation(agent):
    with agent._execution_start_lock:
        assert agent.start_local_run({'script_id': 1}) == {'error': 'another task is running'}
        agent.poll_and_execute()


def test_local_request_during_online_preparation_cannot_start(agent, monkeypatch):
    cache(agent, monkeypatch)
    legacy(agent, monkeypatch, {'id': 7, 'script_id': 1, 'script_version': 1, 'params': {'choice': 'old'}})
    entered = threading.Event()
    release = threading.Event()
    attempted = []
    def prepare(*a, **kw):
        attempted.append(agent.start_local_run({'script_id': 1}))
        entered.set()
        release.wait(2)
        raise RuntimeError('mock prepare ends')
    monkeypatch.setattr(agent, 'prepare_environment', prepare)
    agent.poll_and_execute()
    assert entered.wait(1)
    assert attempted == [{'error': 'another task is running'}]
    release.set()
    agent._controller.worker.join(2)


def test_processes_have_distinct_parameter_files(agent, monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(agent, 'spawn_contained', lambda command, **kw: commands.append(command) or SimpleNamespace(pid=len(commands)))
    a = agent._start_script_subprocess(str(tmp_path), {'value': 1}, str(tmp_path / 'a.log'), 10)
    b = agent._start_script_subprocess(str(tmp_path), {'value': 2}, str(tmp_path / 'b.log'), 10)
    try:
        assert a._params_file != b._params_file
        for proc, value, command in ((a, 1, commands[0]), (b, 2, commands[1])):
            with open(proc._params_file, encoding='utf-8') as stream:
                assert json.load(stream) == {'value': value}
            assert command[-1] == proc._params_file
    finally:
        a._log_file.close()
        b._log_file.close()


def test_failed_spawn_cleans_its_parameter_file(agent, monkeypatch, tmp_path):
    monkeypatch.setattr(agent, 'spawn_contained', Mock(side_effect=OSError('spawn failed')))
    with pytest.raises(OSError):
        agent._start_script_subprocess(str(tmp_path), {}, str(tmp_path / 'a.log'), 10)
    assert not list(tmp_path.glob('params-*.json'))


@pytest.mark.parametrize('failure', ['log-open', 'serialization'])
def test_pre_spawn_failure_cleans_parameter_file(agent, tmp_path, failure):
    log_path = tmp_path / 'a.log'
    params = {}
    if failure == 'log-open':
        log_path.mkdir()
    else:
        params = {'invalid': object()}
    with pytest.raises((OSError, TypeError)):
        agent._start_script_subprocess(str(tmp_path), params, str(log_path), 10)
    assert not list(tmp_path.glob('params-*.json'))


def local_record():
    return {'script_id': 1, 'script_version': 1, 'status': 'success', 'params': {},
            'started_at': 100, 'finished_at': 101, 'log_path': 'fake.log', 'synced': False, 'backend_run_id': None}


def online(agent, monkeypatch):
    agent._task_device.registered = {'id': 3}
    agent._task_device.identity = {'device_secret': 'mock'}
    monkeypatch.setattr(agent, '_last_online_time', agent.time.time())
    monkeypatch.setattr(agent, '_agent_id', 3)


@pytest.mark.parametrize('failure', ['network', 'response-lost', 'log-changed'])
def test_sync_retries_same_backend_record_after_failure(agent, monkeypatch, failure):
    online(agent, monkeypatch)
    agent._local_runs['L1'] = local_record()
    calls = []
    def request(method, route, payload, headers):
        assert route == '/api/runs/import-local'
        calls.append(json.loads(json.dumps(payload)))
        if len(calls) == 1:
            raise agent.requests.Timeout(failure)
        return {'run_id': 7}
    monkeypatch.setattr(agent, '_task_request', request)
    monkeypatch.setattr(agent, '_log_tail', lambda path: 'first')
    agent._sync_local_runs_to_backend()
    agent._load_local_runs()
    monkeypatch.setattr(agent, '_log_tail', lambda path: 'changed')
    agent._sync_local_runs_to_backend()
    assert calls[0] == calls[1]
    assert agent._local_runs['L1']['backend_run_id'] == 7
    assert agent._local_runs['L1']['synced'] is True


def test_sync_does_not_overwrite_another_agents_run(agent, monkeypatch):
    online(agent, monkeypatch)
    agent._local_runs['L1'] = dict(local_record(), backend_run_id=7)
    def request(method, route, *a):
        assert method == 'GET'
        return {'id': 7, 'agent_id': 99, 'status': 'running', 'script_id': 1, 'script_version': 1}
    monkeypatch.setattr(agent, '_task_request', request)
    agent._sync_local_runs_to_backend()
    assert agent._local_runs['L1']['synced'] is False


def test_sync_finishes_cancelled_unclaimed_import_without_changing_status(agent, monkeypatch):
    online(agent, monkeypatch)
    agent._local_runs['L1'] = dict(local_record(), backend_run_id=7)
    def request(method, route, *a):
        assert method == 'GET'
        return {'id': 7, 'agent_id': None, 'status': 'cancelled', 'script_id': 1, 'script_version': 1}
    monkeypatch.setattr(agent, '_task_request', request)
    agent._sync_local_runs_to_backend()
    assert agent._local_runs['L1']['synced'] is True


def test_poll_never_executes_pending_local_history_import(agent, monkeypatch):
    calls = legacy(agent, monkeypatch, {'id': 7, 'script_id': 1})
    agent._local_runs['L1'] = dict(local_record(), backend_run_id=7)
    agent.poll_and_execute()
    assert all(not route.endswith('/claim') for _, route, _ in calls)


def test_legacy_import_log_exception_still_finishes_owned_running_record(agent, monkeypatch):
    online(agent, monkeypatch)
    agent._local_runs['L1'] = dict(local_record(), backend_run_id=7)
    monkeypatch.setattr(agent, '_finish_log_upload', Mock(side_effect=OSError('log unreadable')))
    calls = []
    def request(method, route, payload=None):
        calls.append((method, route, payload))
        if method == 'GET':
            return {'id': 7, 'agent_id': 3, 'status': 'running', 'script_id': 1, 'script_version': 1}
        assert method == 'PATCH' and route == '/api/runs/7/status'
        assert payload['status'] == 'success'
        return {}
    monkeypatch.setattr(agent, '_task_request', request)
    agent._sync_local_runs_to_backend()
    assert [method for method, _, _ in calls] == ['GET', 'PATCH']
    assert agent._local_runs['L1']['synced'] is False


def test_log_exception_still_reports_terminal_status(agent, monkeypatch):
    monkeypatch.setattr(agent, '_finish_log_upload', Mock(side_effect=OSError('log unreadable')))
    agent._complete_task({'id': 'B7', 'source': 'legacy', 'body': {'run_id': 7}, 'state': 'success', 'log_path': 'missing'})
    reports = []
    agent._task_store.flush(lambda route, payload: reports.append(payload) or True)
    assert reports[0]['status'] == 'success'
