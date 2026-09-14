"""Isolated ledger/controller tests: never launch scripts or contact a server."""
import threading
from datetime import datetime, timezone, timedelta

import pytest

from client.runtime.task_store import TaskStore
from client.runtime.execution_control import ExecutionController, ExecutionGate
from client.runtime.process_tree import StopUnconfirmed


@pytest.fixture
def store(tmp_path):
    value = TaskStore(tmp_path / 'tasks.sqlite3')
    yield value
    value.close()


def body(**extra):
    return {'name': '测试', 'script_id': 1, 'script_version': 2, 'params': {},
            'trigger': {'kind': 'daily', 'timezone': 'Asia/Shanghai', 'time': '10:00'}, **extra}


def test_pause_delete_cancel_queued_resume_refreshes(store):
    now = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    task = store.create(body(), now)
    import uuid
    event = store.action(task['id'], {'action': 'run', 'request_id': str(uuid.uuid4())}, now)
    store.action(task['id'], {'action': 'pause'}, now)
    assert store.events()[0]['state'] == 'cancelled'
    with pytest.raises(ValueError, match='暂停'):
        store.action(task['id'], {'action': 'run', 'request_id': str(uuid.uuid4())})
    with pytest.raises(ValueError):
        store.intent(event['id'], {})
    store.action(task['id'], {'action': 'resume'}, now + timedelta(days=2))
    assert datetime.fromisoformat(store.tasks()[0]['next_fire_at']) > now + timedelta(days=2)
    store.action(task['id'], {'action': 'delete'}, now)
    assert store.tasks() == []


def test_manual_idempotency_and_offline_once_skip(store):
    import uuid
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    task = store.create(body(trigger={'kind': 'once', 'timezone': 'Asia/Shanghai',
                                    'start_at': (now - timedelta(hours=1)).isoformat(), 'misfire': 'skip'}), now)
    store.tick(now)
    assert store.events()[0]['state'] == 'skipped'
    req = {'action': 'run', 'request_id': str(uuid.uuid4())}
    assert store.action(task['id'], req, now)['id'] == store.action(task['id'], req, now)['id']
    store.tick(now + timedelta(days=1))
    assert len(store.events()) == 2


def test_periodic_tick_only_latest_occurrence_and_utc_storage(store):
    now = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    task = store.create(body(), now)
    store.tick(now + timedelta(days=10, hours=1))
    assert len(store.events()) == 1
    assert store.events()[0]['state'] == 'queued'
    assert store.tasks()[0]['next_fire_at'].endswith('+00:00')
    store.tick(now + timedelta(days=10, hours=1))
    assert len(store.events()) == 1


def test_recovery_never_requeues_and_keeps_terminal_outbox(store):
    store.intent('L1', {})
    attempt = store.attempt(7, {})
    assert store.attempt(7, {}) == attempt
    store.attempt_state(7, 'start_intent')
    assert store.recover()[0]['attempt_id'] == attempt
    assert store.events()[0]['state'] == 'unknown'
    assert store.queued() == []
    store.finish_attempt(7, {}, {'state': 'success', 'stopped': True, 'attempt_id': attempt})
    assert store.recover() == []
    sent = []
    store.flush(lambda route, payload: sent.append(payload) or False)
    store.flush(lambda route, payload: sent.append(payload) or True)
    assert [p['state'] for p in sent] == ['success', 'success']


def test_prepare_reserves_slot_and_cancel_never_spawns(store):
    entered = threading.Event()
    completed = []
    def prepare(item):
        assert store.events()[0]['state'] == 'preparing'
        entered.set()
        item['cancel'].wait(2)
        return 'python'
    controller = ExecutionController(store, prepare, lambda *a: pytest.fail('must not spawn'), completed.append)
    controller.submit('L1', body())
    assert entered.wait(1)
    assert controller.submit('L2', body()) == {'error': 'another task is running'}
    assert controller.cancel('L1')['status'] == 'cancel_requested'
    controller.worker.join(2)
    assert completed[0]['state'] == 'cancelled'
    assert controller.active is None


def test_start_ack_loss_never_spawns_or_replays(store):
    attempt = store.attempt(4, {})
    calls = []
    def ack(item):
        calls.append(item)
        assert store.attempts()[0]['state'] == 'start_intent'
        raise TimeoutError('lost ACK')
    controller = ExecutionController(store, lambda item: 'python', lambda *a: pytest.fail('must not spawn'),
                                     lambda item: None, ack)
    request = body(execution_id=4, attempt_id=attempt)
    controller.submit('R4', request, 'remote')
    controller.worker.join(2)
    assert store.events()[0]['state'] == 'unknown'
    with pytest.raises(ValueError):
        controller.submit('R4', request, 'remote')
    assert len(calls) == 1


def test_unconfirmed_preparation_stop_latches_slot(store):
    def prepare(item):
        raise StopUnconfirmed('cannot verify')
    controller = ExecutionController(store, prepare, lambda *a: None, lambda *a: pytest.fail('must not report stopped'))
    controller.submit('L1', body())
    controller.worker.join(2)
    assert controller.active['state'] == 'unknown'
    assert controller.active['stopped'] is False
    assert 'error' in controller.submit('L2', body())


def test_timeout_uses_monotonic_not_wall_clock(store, monkeypatch):
    from client.runtime import execution_control as module
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    def prepare(item):
        clock[0] += 2
        return 'python'
    completed = []
    controller = ExecutionController(store, prepare, lambda *a: pytest.fail('must not spawn'), completed.append)
    controller.submit('L1', body(timeout_seconds=1))
    controller.worker.join(2)
    assert completed[0]['state'] == 'failed'
    assert '超时' in completed[0]['error_msg']


def test_lifetime_gate_cannot_be_stolen(tmp_path):
    gate = ExecutionGate(tmp_path / 'execution.lock')
    try:
        with pytest.raises(RuntimeError):
            ExecutionGate(tmp_path / 'execution.lock')
    finally:
        gate.close()
    ExecutionGate(tmp_path / 'execution.lock').close()


def test_completed_parent_still_stops_descendants_before_report(store, tmp_path, monkeypatch):
    from client.runtime import execution_control as module
    from types import SimpleNamespace
    order = []
    param_file = tmp_path / 'params.json'
    param_file.write_text('{}')
    proc = SimpleNamespace(poll=lambda: 0, returncode=0, _log_file=SimpleNamespace(close=lambda: order.append('close')),
                           _params_file=str(param_file))
    monkeypatch.setattr(module, 'stop_process_tree', lambda proc: order.append('tree-empty'))
    controller = ExecutionController(store, lambda item: 'python', lambda *a: proc,
                                     lambda item: order.append('report'))
    controller.submit('L1', body())
    controller.worker.join(2)
    assert order == ['tree-empty', 'close', 'report']
    assert controller.active is None


def test_stop_failure_after_process_exit_does_not_report_or_release(store, monkeypatch):
    from client.runtime import execution_control as module
    from types import SimpleNamespace
    def stop(proc):
        raise StopUnconfirmed('child remains')
    monkeypatch.setattr(module, 'stop_process_tree', stop)
    controller = ExecutionController(store, lambda item: None,
                                     lambda *a: SimpleNamespace(poll=lambda: 0, returncode=0),
                                     lambda *a: pytest.fail('must not report stopped'))
    controller.submit('L1', body())
    controller.worker.join(2)
    assert controller.active['state'] == 'unknown'
    assert controller.active['stopped'] is False


def test_unknown_pauses_schedule_and_cancels_other_queued(store):
    import uuid
    task = store.create(body())
    event = store.action(task['id'], {'action': 'run', 'request_id': str(uuid.uuid4())})
    store.intent(event['id'], event['body'])
    store.action(task['id'], {'action': 'run', 'request_id': str(uuid.uuid4())})
    store.state(event['id'], 'unknown')
    assert store.tasks()[0]['enabled'] is False
    assert store.queued() == []


def test_recovery_unknown_pauses_associated_schedule(store):
    import uuid
    task = store.create(body())
    event = store.action(task['id'], {'action': 'run', 'request_id': str(uuid.uuid4())})
    store.intent(event['id'], {})
    store.recover()
    assert store.tasks()[0]['enabled'] is False


def test_queued_occurrence_cannot_start_hours_after_due(store):
    now = datetime.now(timezone.utc) - timedelta(hours=3)
    task = store.create(body(trigger={'kind': 'once', 'timezone': 'UTC',
        'start_at': now.isoformat(), 'misfire': 'run_once', 'grace_seconds': 60}), now - timedelta(seconds=1))
    store.tick(now)
    event = store.queued()[0]
    with pytest.raises(ValueError, match='宽限窗口'):
        store.intent(event['id'], event['body'])
    store.fail_queued(event['id'], '发生项已超出宽限窗口')
    assert store.events()[0]['state'] == 'skipped'


def test_manual_occurrence_expires_after_300_seconds(store):
    import uuid
    task = store.create(body())
    event = store.action(task['id'], {'action': 'run', 'request_id': str(uuid.uuid4())},
                         datetime.now(timezone.utc) - timedelta(seconds=301))
    with pytest.raises(ValueError, match='300 秒宽限窗口'):
        store.intent(event['id'], {})


def test_terminal_persistence_failure_latches_execution_slot(store):
    def complete(item):
        raise OSError('disk unavailable')
    controller = ExecutionController(store, lambda item: (_ for _ in ()).throw(ValueError('invalid params')),
                                     lambda *a: pytest.fail('must not spawn'), complete)
    controller.submit('L1', body())
    controller.worker.join(2)
    assert controller.active['stopped'] is True
    assert controller.active['persistence_error'] == 'OSError'
    assert controller.submit('L2', body()) == {'error': 'another task is running'}


def test_spawn_windows_is_suspended_until_job_assignment(monkeypatch):
    from client.runtime import process_tree as module
    from types import SimpleNamespace
    order = []
    class Tree:
        def __init__(self, name):
            pass
        def attach(self, pid):
            order.append('attach')
        def close(self):
            order.append('close')
    class Resume:
        def __call__(self, handle):
            order.append('resume')
            return 0
    def popen(args, **kw):
        assert kw['creationflags'] & 4
        order.append('spawn-suspended')
        return SimpleNamespace(pid=17, _handle=22)
    monkeypatch.setattr(module, 'ProcessTree', Tree)
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    monkeypatch.setattr(module.ctypes, 'WinDLL', lambda name: SimpleNamespace(NtResumeProcess=Resume()))
    proc = module.spawn_contained(['mock-python'])
    assert order == ['spawn-suspended', 'attach', 'resume']
    assert proc._process_tree is not None
