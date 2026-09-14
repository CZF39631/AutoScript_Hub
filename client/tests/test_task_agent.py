"""Agent integration with temporary ClientPaths, mocked networking and no child processes."""
import importlib
import json
import threading
from types import SimpleNamespace

import pytest

from client.runtime.paths import ClientPaths


@pytest.fixture
def agent(tmp_path, monkeypatch):
    paths = ClientPaths.from_environment(install_dir=tmp_path / 'install', data_dir=tmp_path / 'data')
    paths.ensure()
    monkeypatch.setattr(ClientPaths, 'from_environment', classmethod(lambda cls, **kw: paths))
    module = importlib.import_module('client.agent.main')
    monkeypatch.setattr(module, '_CLIENT_PATHS', paths)
    monkeypatch.setattr(module, '_SCRIPTS_DIR', str(paths.scripts_dir))
    monkeypatch.setattr(module, '_LOGS_DIR', str(paths.logs_dir))
    monkeypatch.setattr(module, '_local_runs_file', str(paths.runs_dir / 'local_runs.json'))
    monkeypatch.setattr(module, 'SCRIPT_AUTHORIZATIONS_FILE', str(paths.config_dir / 'script_authorizations.json'))
    monkeypatch.setattr(module, '_client_config', {'username': 'isolated'})
    for key in ('_task_store', '_task_device', '_controller', '_lifetime_gate', '_token', '_last_online_time'):
        monkeypatch.setattr(module, key, None)
    monkeypatch.setattr(module, '_local_runs', {})
    monkeypatch.setattr(module, '_running_proc', None)
    monkeypatch.setattr(module, '_local_run_proc', None)
    monkeypatch.setattr(module, '_execution_start_lock', threading.Lock())
    monkeypatch.setattr(module, '_shutdown_when_idle', False)
    monkeypatch.setattr(module, '_notify_execution_result', lambda *a: None)
    for method in ('get', 'post', 'patch', 'request'):
        monkeypatch.setattr(module.requests, method, lambda *a, **kw: pytest.fail('real networking forbidden'))
    monkeypatch.setattr(module, 'ProcessTree', lambda *a: SimpleNamespace(stop=lambda: None, confirm_stopped=lambda: None, close=lambda: None))
    module._initialize_tasks()
    yield module
    if module._controller.worker:
        if module._controller.active:
            module._controller.active['cancel'].set()
        module._controller.worker.join(2)
        assert not module._controller.worker.is_alive()
    module._task_store.close()
    module._lifetime_gate.close()


def cache(agent, monkeypatch):
    monkeypatch.setattr(agent, '_load_authorized_script_ids', lambda: {1})
    for version in (1, 2):
        path = agent._CLIENT_PATHS.scripts_dir / '1' / str(version)
        path.mkdir(parents=True)
        (path / 'main.py').write_text('# mock config parser only', encoding='utf-8')
    monkeypatch.setattr(agent, 'parse_script_config', lambda path: {'name': '测试', 'params': [
        {'key': 'choice', 'label': '选项', 'type': 'select', 'options': ['old' if '/1/main.py' in str(path).replace('\\', '/') else 'new'], 'required': True}]})


def test_fixed_version_validation_and_no_environment_override(agent, monkeypatch):
    cache(agent, monkeypatch)
    assert '参数校验' in agent.start_local_run({'script_id': 1, 'script_version': 1, 'params': {'choice': 'new'}})['error']
    assert '环境变量' in agent.start_local_run({'script_id': 1, 'env_vars': {'PYTHONPATH': 'evil'}})['error']
    assert agent._task_store.events() == []


def test_local_schedule_api_arrays_pause_and_offline_tick(agent, monkeypatch):
    cache(agent, monkeypatch)
    task = agent._local_task_api('POST', '/local/schedules', {'name': '测试任务', 'script_id': 1,
        'script_version': 1, 'params': {'choice': 'old'}, 'trigger': {'kind': 'manual', 'timezone': 'Asia/Shanghai'}})
    import uuid
    agent._local_task_api('POST', '/local/schedules/' + task['id'] + '/action',
                          {'action': 'run', 'request_id': str(uuid.uuid4())})
    agent._local_task_api('POST', '/local/schedules/' + task['id'] + '/action', {'action': 'pause'})
    agent._check_local_runs()
    assert isinstance(agent._local_task_api('GET', '/local/schedules'), list)
    events = agent._local_task_api('GET', '/local/schedule-events')
    assert events[0]['state'] == 'cancelled'
    assert events[0]['task_name'] == '测试任务'
    assert events[0]['local_run_id'] is None
    assert agent._local_task_api('GET', '/local/device-grants') == []


def test_history_import_is_terminal_uuid_device_authenticated(agent, monkeypatch):
    import uuid
    import time
    device = agent._task_device
    device.registered = {'id': 3}
    device.identity = {'device_secret': 'mock-only', 'scope': device.scope}
    monkeypatch.setattr(agent, '_last_online_time', time.time())
    rec = {'script_id': 1, 'script_version': 2, 'status': 'cancelled', 'params': {},
           'started_at': 1000, 'finished_at': 1001, 'result_files': [{'path': 'result.txt'}]}
    agent._local_runs['L1'] = rec
    calls = []
    def request(method, route, payload, headers):
        assert json.loads(open(agent._local_runs_file, encoding='utf-8').read())['L1']['request_id'] == payload['request_id']
        calls.append((method, route, payload, headers))
        return {'id': 9, 'run_id': 9, 'status': 'cancelled', 'imported': True}
    monkeypatch.setattr(agent, '_task_request', request)
    agent._sync_local_runs_locked()
    method, route, payload, headers = calls[0]
    assert (method, route) == ('POST', '/api/runs/import-local')
    uuid.UUID(payload['request_id'])
    assert payload['started_at'].endswith('+00:00')
    assert payload['result_files'] == ['result.txt']
    assert headers == {'X-Device-Token': 'mock-only'}
    assert rec['synced'] is True
    agent._sync_local_runs_locked()
    assert len(calls) == 1


def test_prepare_does_not_block_main_heartbeat(agent, monkeypatch):
    cache(agent, monkeypatch)
    entered = threading.Event()
    def prepare(item):
        entered.set()
        item['cancel'].wait(2)
        return 'mock-python'
    monkeypatch.setattr(agent._controller, 'prepare', prepare)
    monkeypatch.setattr(agent._controller, 'spawn', lambda *a: pytest.fail('cancelled prepare must not spawn'))
    rec = agent.start_local_run({'script_id': 1, 'script_version': 1, 'params': {'choice': 'old'}})
    assert entered.wait(1)
    monkeypatch.setattr(agent, '_token', 'mock')
    monkeypatch.setattr(agent, '_last_update_check_time', 10**20)
    monkeypatch.setattr(agent, '_last_settings_sync_time', 10**20)
    monkeypatch.setattr(agent, '_last_script_access_sync_time', 10**20)
    monkeypatch.setattr(agent, '_flush_pending_reports', lambda: None)
    monkeypatch.setattr(agent, '_flush_pending_log_uploads', lambda: None)
    monkeypatch.setattr(agent, 'poll_and_execute', lambda: None)
    beats = []
    monkeypatch.setattr(agent, 'send_heartbeat', lambda: beats.append(True) or True)
    assert agent.agent_iteration('mock', 'mock') is True
    assert beats == [True]
    agent._local_task_api('POST', '/local/runs/' + rec['local_run_id'] + '/cancel', {})
    agent._controller.worker.join(2)
    assert rec['status'] == 'cancelled'


def test_local_task_route_requires_bearer_and_origin(agent):
    from client.agent.local_server import AgentHandler
    calls = []
    class Handler(AgentHandler):
        api_token = 'test-local-only'
        task_api_fn = staticmethod(lambda *a: calls.append(a) or [])
        def _json(self, payload, code=200):
            self.result = (payload, code)
    handler = object.__new__(Handler)
    handler.path = '/local/schedules'
    handler.headers = {'Origin': 'https://untrusted.invalid', 'Authorization': 'Bearer test-local-only'}
    handler.do_GET()
    assert handler.result[1] == 403
    handler.headers = {}
    handler.do_GET()
    assert handler.result[1] == 401
    assert calls == []
    handler.headers = {'Authorization': 'Bearer test-local-only'}
    handler.do_GET()
    assert handler.result == ([], 200)


def test_device_public_never_returns_secret(agent):
    device = agent._task_device
    device.identity = {'device_uuid': 'public', 'device_secret': 'never-public', 'scope': device.scope}
    device.registered = {'id': 3, 'name': 'mock', 'device_secret': 'never-public'}
    value = device.public()
    assert value['registered'] is True
    assert 'secret' not in json.dumps(value)


def test_remote_claim_start_ack_loss_reports_unknown_without_execute(agent, monkeypatch):
    cache(agent, monkeypatch)
    monkeypatch.setattr(agent, '_agent_id', None)
    monkeypatch.setattr(agent, 'prepare_environment', lambda *a, **kw: 'mock-python')
    monkeypatch.setattr(agent._controller, 'spawn', lambda *a: pytest.fail('lost ACK must not spawn'))
    agent._task_device.registered = {'id': 3}
    calls = []
    def device_call(method, suffix, body=None):
        calls.append((suffix, body))
        if suffix == '/pending':
            return [{'id': 7, 'run_id': 8, 'state': 'queued'}]
        if suffix.endswith('/claim'):
            assert agent._task_store.attempts()[0]['state'] == 'claim_intent'
            return {'id': 7, 'run_id': 8, 'state': 'claimed', 'script_id': 1, 'script_version': 1,
                    'params': {'choice': 'old'}, 'timeout_seconds': 3600}
        if suffix.endswith('/start'):
            assert agent._task_store.attempts()[0]['state'] == 'start_intent'
            raise TimeoutError('ACK lost')
        return {}
    monkeypatch.setattr(agent._task_device, 'call', device_call)
    agent.poll_and_execute()
    agent._controller.worker.join(2)
    assert agent._task_store.events()[0]['state'] == 'unknown'
    agent.poll_and_execute()
    reports = [payload for suffix, payload in calls if suffix.endswith('/report')]
    assert reports[0]['state'] == 'unknown'
    assert reports[0]['stopped'] is True
    assert sum(s.endswith('/claim') for s, _ in calls) == 1
    assert sum(s.endswith('/start') for s, _ in calls) == 1


def test_initializer_is_singleton_under_concurrent_http_calls(agent, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    agent._task_store.close()
    agent._lifetime_gate.close()
    for name in ('_task_store', '_task_device', '_controller', '_lifetime_gate'):
        monkeypatch.setattr(agent, name, None)
    original = agent._initialize_tasks_locked
    calls = []
    def initialize():
        calls.append(True)
        original()
    monkeypatch.setattr(agent, '_initialize_tasks_locked', initialize)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: agent._initialize_tasks(), range(16)))
    assert calls == [True]
    assert agent._controller is not None


def test_initializer_failure_releases_gate_for_retry(agent, monkeypatch):
    agent._task_store.close()
    agent._lifetime_gate.close()
    for name in ('_task_store', '_task_device', '_controller', '_lifetime_gate'):
        monkeypatch.setattr(agent, name, None)
    original = agent.TaskStore
    monkeypatch.setattr(agent, 'TaskStore', lambda *a: (_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises(OSError):
        agent._initialize_tasks()
    assert agent._lifetime_gate is None
    monkeypatch.setattr(agent, 'TaskStore', original)
    agent._initialize_tasks()
    assert agent._controller is not None


def test_offline_grants_cache_does_not_break_local_ui(agent, monkeypatch):
    device = agent._task_device
    device.registered = {'id': 3}
    device.identity = {'device_uuid': 'mock', 'scope': device.scope}
    monkeypatch.setattr(device, 'call', lambda *a: [{'id': 8}])
    assert device.grants() == [{'id': 8}]
    def offline(*a):
        raise ConnectionError('offline')
    monkeypatch.setattr(device, 'call', offline)
    assert agent._local_task_api('GET', '/local/device-grants') == [{'id': 8}]
    assert device.public()['grants_online'] is False
    with pytest.raises(ConnectionError):
        device.decision(8, {'decision': 'accept'})


def test_bad_result_marker_cannot_drop_completion_report(agent, monkeypatch):
    monkeypatch.setattr(agent, '_log_tail', lambda path: "__RESULT__:['bad\\\\x00path']")
    monkeypatch.setattr(agent, '_normalize_result_files', lambda *a: (_ for _ in ()).throw(ValueError('bad literal')))
    agent._complete_task({'id': 'B7', 'source': 'legacy', 'body': {'run_id': 7}, 'state': 'success'})
    reports = []
    agent._task_store.flush(lambda route, payload: reports.append(payload) or True)
    assert reports[0]['status'] == 'success'
    assert reports[0]['result_files'] == '[]'


def test_diagnostic_policy_failure_resets_safe_defaults(agent, monkeypatch):
    monkeypatch.setattr(agent, '_token', 'mock')
    monkeypatch.setattr(agent, '_last_update_check_time', 10**20)
    monkeypatch.setattr(agent, '_last_settings_sync_time', 0)
    monkeypatch.setattr(agent, '_last_script_access_sync_time', 10**20)
    for name in ('_flush_pending_reports', '_flush_pending_log_uploads', 'poll_and_execute', 'send_heartbeat', '_sync_client_settings'):
        monkeypatch.setattr(agent, name, lambda: None)
    def unavailable(*a, **kw):
        raise TimeoutError('offline')
    monkeypatch.setattr(agent, '_task_request', unavailable)
    policies = []
    monkeypatch.setattr(agent, 'update_effective_policy', policies.append)
    agent.agent_iteration('mock', 'mock')
    assert policies == [{}]


def test_explicit_claim_rejection_never_creates_impossible_reports(agent, monkeypatch):
    response = agent.requests.Response()
    response.status_code = 409
    def rejected(*args):
        raise agent.requests.HTTPError(response=response)
    monkeypatch.setattr(agent._task_device, 'call', rejected)
    item = {'id': 'R77', 'source': 'remote', 'body': {'execution_id': 77}, 'state': 'failed'}
    with pytest.raises(agent.requests.HTTPError):
        agent._prepare_task(item)
    agent._complete_task(item)
    sent = []
    agent._task_store.flush(lambda *args: sent.append(args) or True)
    assert not sent
    assert not agent._task_store.recover()


def test_log_tail_drops_partial_credential_line(agent, tmp_path):
    log = tmp_path / 'long.log'
    log.write_bytes(b'Authorization: Bearer ' + b'x' * 70000 + b'\nfinished\n')
    assert agent._log_tail(str(log)) == 'finished\n'
