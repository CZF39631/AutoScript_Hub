"""调度接线测试：隔离测试库，不启动后台线程或真实客户端。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app import scheduler
from app.models import Agent, Run, Script, User, TaskDevice, ScheduledTask, TaskExecution


def test_iteration_keeps_other_jobs_running_after_failure(monkeypatch):
    called = []

    def broken():
        called.append('heartbeat')
        raise RuntimeError('isolated failure')

    monkeypatch.setattr(scheduler, '_heartbeat_scan', broken)
    for name in ('_task_stale_scan', '_task_dispatch', '_diagnostic_cleanup', '_maybe_log_cleanup'):
        monkeypatch.setattr(scheduler, name, lambda name=name: called.append(name))
    scheduler._scheduler_iteration()
    assert called == ['heartbeat', '_task_stale_scan', '_task_dispatch', '_diagnostic_cleanup', '_maybe_log_cleanup']


def test_watchdog_preserves_managed_run_until_device_confirms_stop(fresh_db, monkeypatch):
    session, _ = fresh_db
    now = datetime.now(timezone.utc)
    with session() as db:
        user = User(username='managed-watchdog', display_name='Watchdog', password_hash='unused', role='operator', status='active')
        script = Script(name='managed-watchdog', type='py', latest_version=1, status='active')
        db.add_all([user, script])
        db.flush()
        agent = Agent(machine_name='test-only', user_id=user.id, status='online', last_heartbeat=now - timedelta(minutes=5))
        device = TaskDevice(device_uuid=str(uuid4()), secret_hash='0' * 64, user_id=user.id, name='test-only', status='online', last_heartbeat=now - timedelta(minutes=5))
        db.add_all([agent, device])
        db.flush()
        task = ScheduledTask(name='test', requester_id=user.id, device_id=device.id, script_id=script.id, script_version=1, trigger='{"kind":"manual","timezone":"UTC"}')
        run = Run(script_id=script.id, script_version=1, user_id=user.id, agent_id=agent.id, status='running', started_at=now - timedelta(minutes=2))
        db.add_all([task, run])
        db.flush()
        execution = TaskExecution(task_id=task.id, device_id=device.id, run_id=run.id, revision=1, state='running', attempt_id=str(uuid4()))
        db.add(execution)
        db.flush()
        device.active_execution_id = execution.id
        ids = run.id, task.id, device.id, execution.id
        db.commit()

    monkeypatch.setattr(scheduler, 'SessionLocal', session)
    scheduler._heartbeat_scan()
    with session() as db:
        assert db.get(Run, ids[0]).status == 'running'
    scheduler._task_stale_scan()
    with session() as db:
        assert db.get(Run, ids[0]).status == 'unknown'
        assert db.get(Run, ids[0]).finished_at is None
        assert not db.get(ScheduledTask, ids[1]).enabled
        assert db.get(TaskDevice, ids[2]).active_execution_id == ids[3]
        assert not db.get(TaskExecution, ids[3]).stopped
