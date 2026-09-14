"""仅数据库/HTTP 协议测试；不执行脚本、不连接生产。"""
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import create_access_token
from app.database import get_db
from app.models import (User, Group, Script, ScriptVersion, TaskDevice, DeviceGrant,
                        ScheduledTask, TaskExecution, Run, LocalRunImport)
from app.routers import tasks, runs
from app.schemas import TaskCreate, TaskAction, TaskReport, LocalRunImportRequest
from app.services import task_service as s


@pytest.fixture
def setup(fresh_db, monkeypatch, tmp_path):
    factory, engine = fresh_db
    monkeypatch.setattr("app.config.LOGS_DIR", str(tmp_path / "logs"))
    db = factory()
    group = Group(name="任务测试组")
    owner = User(username="owner", display_name="本机", password_hash="unused", groups=[group])
    actor = User(username="actor", display_name="申请人", password_hash="unused", groups=[group])
    admin = User(username="root", display_name="管理员", password_hash="unused", role="admin")
    script = Script(name="固定版本", latest_version=2, groups=[group], config_json='{"params":[{"name":"new","required":true}]}')
    db.add_all([owner, actor, admin, script])
    db.flush()
    db.add(ScriptVersion(script_id=script.id, version=1, file_path="unused", config_json='{"params":[]}'))
    device = TaskDevice(device_uuid=str(uuid4()), secret_hash=s.digest("s" * 32), user_id=owner.id, name="设备")
    db.add(device)
    db.flush()
    grant = DeviceGrant(device_id=device.id, requester_id=actor.id, script_id=script.id, script_version=1, status="accepted")
    db.add(grant)
    db.commit()
    task_data = dict(name="测试任务", device_id=device.id, script_id=script.id, script_version=1, trigger={"kind":"manual"})
    task_id = s.create_task(db, TaskCreate(**task_data), actor)["id"]
    task = db.get(ScheduledTask, task_id)
    app = FastAPI()
    app.include_router(tasks.router)
    app.include_router(runs.router)
    def dependency():
        session = factory()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = dependency
    api = TestClient(app)
    def headers(user=owner, token=True):
        result = {"Authorization": "Bearer " + create_access_token(user.id, user.role)}
        if token:
            result["X-Device-Token"] = "s" * 32
        return result
    yield db, device, actor, owner, admin, task, grant, api, headers
    api.close()
    db.close()


def enqueue(db, task):
    result = s.task_action(db, task, TaskAction(action="run", request_id=uuid4()))
    return db.get(TaskExecution, result["id"])


def test_device_token_and_owner_required_even_admin(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    path = f"/api/task-devices/{device.id}/pending"
    assert api.get(path).status_code == 401
    assert api.get(path, headers=headers(token=False)).status_code == 403
    assert api.get(path, headers=headers(admin)).status_code == 403
    assert api.get(path, headers=headers(actor)).status_code == 403
    assert api.get(path, headers=headers()).status_code == 200
    registration = dict(device_uuid=device.device_uuid, device_secret="x" * 32, name="盗用")
    assert api.post("/api/task-devices/register", json=registration, headers=headers()).status_code == 403
    registration["device_secret"] = "s" * 32
    assert api.post("/api/task-devices/register", json=registration, headers=headers(admin)).status_code == 403
    assert api.post("/api/task-devices/register", json=registration, headers=headers()).json()["id"] == device.id


def test_manual_dedupe_and_single_slot_start_once(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    req = TaskAction(action="run", request_id=uuid4())
    first = s.task_action(db, task, req)
    assert s.task_action(db, task, req)["id"] == first["id"]
    assert db.query(Run).count() == 1
    execution = db.get(TaskExecution, first["id"])
    other = enqueue(db, task)
    attempt = str(uuid4())
    assert s.claim(db, device, execution, attempt)["state"] == "claimed"
    assert s.claim(db, device, execution, attempt)["attempt_id"] == attempt
    with pytest.raises(HTTPException):
        s.claim(db, device, execution, str(uuid4()))
    db.rollback()
    with pytest.raises(HTTPException):
        s.claim(db, device, other, str(uuid4()))
    db.rollback()
    assert s.start(db, device, execution, attempt)["can_start"] is True
    assert s.start(db, device, execution, attempt)["can_start"] is False
    assert db.get(Run, execution.run_id).user_id == actor.id


@pytest.mark.parametrize("victim", ["owner", "actor"])
@pytest.mark.parametrize("phase", ["create", "claim", "start"])
def test_fixed_version_requires_both_users_at_each_stage(setup, victim, phase):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    attempt = str(uuid4())
    if phase == "start":
        s.claim(db, device, execution, attempt)
    (owner if victim == "owner" else actor).groups = []
    db.commit()
    if phase == "start":
        assert s.start(db, device, execution, attempt)["can_start"] is False
        assert execution.state == "cancel_requested"
    else:
        with pytest.raises(HTTPException):
            if phase == "claim":
                s.claim(db, device, execution, attempt)
            else:
                s.create_task(db, TaskCreate(name="禁止创建", device_id=device.id, script_id=task.script_id,
                                            script_version=1, trigger={"kind":"manual"}), actor)


def test_revoke_cancels_queue_requests_stop_and_blocks_start(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    running = enqueue(db, task)
    queued = enqueue(db, task)
    attempt = str(uuid4())
    s.claim(db, device, running, attempt)
    path = f"/api/task-devices/{device.id}/grants/{grant.id}/decision"
    assert api.post(path, json={"decision":"revoke"}, headers=headers(admin)).status_code == 403
    assert api.post(path, json={"decision":"revoke"}, headers=headers()).status_code == 200
    db.expire_all()
    assert queued.state == "cancelled" and queued.stopped
    assert running.state == "cancel_requested" and not running.stopped
    assert s.start(db, device, running, attempt)["can_start"] is False
    # 撤销后仍允许持本机凭据上报停止事实，否则永远无法释放槽。
    s.report(db, device, running, TaskReport(attempt_id=attempt, state="cancelled", stopped=True))
    assert device.active_execution_id is None


@pytest.mark.parametrize("phase", ["claim", "start"])
def test_expired_intent_never_starts(setup, phase):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    attempt = str(uuid4())
    if phase == "claim":
        db.get(Run, execution.run_id).created_at = s.now_utc() - timedelta(seconds=301)
        db.commit()
        with pytest.raises(HTTPException):
            s.claim(db, device, execution, attempt)
        assert execution.state == "cancelled"
    else:
        s.claim(db, device, execution, attempt)
        execution.claimed_at = s.now_utc() - timedelta(seconds=task.timeout_seconds + 1)
        db.commit()
        assert not s.start(db, device, execution, attempt)["can_start"]
        assert execution.state == "cancel_requested"
        assert device.active_execution_id == execution.id


def test_unknown_not_restarted_and_terminal_report_idempotent(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    attempt = str(uuid4())
    s.claim(db, device, execution, attempt)
    s.start(db, device, execution, attempt)
    device.last_heartbeat = s.now_utc() - timedelta(seconds=100)
    db.commit()
    assert s.mark_stale_tasks(db, s.now_utc()) == 1
    db.expire_all()
    assert execution.state == "unknown" and not task.enabled
    assert device.active_execution_id == execution.id
    assert not s.start(db, device, execution, attempt)["can_start"]
    req = TaskReport(attempt_id=attempt, state="unknown", stopped=True, log_tail="正常日志")
    s.report(db, device, execution, req)
    assert execution.stopped and device.active_execution_id is None
    s.report(db, device, execution, req)
    s.cancel_execution(db, execution)
    assert execution.state == "unknown"
    with pytest.raises(HTTPException):
        s.report(db, device, execution, TaskReport(attempt_id=attempt, state="success", stopped=True))


def test_old_routes_reject_managed_mutations(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    base = f"/api/runs/{execution.run_id}"
    for method, path, payload in [("post", "/claim", {"agent_id":1}),
                                 ("patch", "/status", {"status":"running"}),
                                 ("post", "/log/chunk", {"offset":0,"content":"bad"}),
                                 ("post", "/cancel", {})]:
        assert getattr(api, method)(base + path, json=payload, headers=headers(actor)).status_code == 409
    assert api.get("/api/runs?status=pending", headers=headers(actor)).json() == []


def test_local_history_terminal_import_deduplicates_and_rejects_conflict(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    now = s.now_utc().isoformat()
    payload = dict(device_id=device.id, request_id=str(uuid4()), script_id=task.script_id,
                   script_version=1, status="success", params={}, started_at=now, finished_at=now, log_tail="导入")
    assert api.post("/api/runs/import-local", json=payload, headers=headers(token=False)).status_code == 403
    first = api.post("/api/runs/import-local", json=payload, headers=headers())
    assert first.status_code == 200, first.text
    duplicate = api.post("/api/runs/import-local", json=payload, headers=headers()).json()
    assert duplicate["run_id"] == first.json()["run_id"] and not duplicate["imported"]
    payload["log_tail"] = "不同内容"
    assert api.post("/api/runs/import-local", json=payload, headers=headers()).status_code == 409
    payload["status"] = "pending"
    assert api.post("/api/runs/import-local", json=payload, headers=headers()).status_code == 422
    assert db.query(LocalRunImport).count() == 1
    assert db.query(Run).filter_by(status="pending").count() == 0
    assert api.patch(f"/api/runs/{duplicate['run_id']}/status", json={"status":"running"}, headers=headers()).status_code == 409


def test_output_utf8_bounds_and_unknown_fields():
    valid = dict(attempt_id=uuid4(), state="success", stopped=True)
    assert len(TaskReport(**valid, log_tail="a" * 65536).log_tail) == 65536
    for extra in ({"log_tail":"中" * 22000}, {"error_msg":"中" * 1400},
                  {"result_files":["a" * 66000]}, {"log_path":"/server/arbitrary"}, {"stopped":False}):
        with pytest.raises(ValidationError):
            TaskReport(**(valid | extra))
    with pytest.raises(ValidationError):
        TaskCreate(name="x", device_id=1, script_id=1, script_version=1, trigger={"kind":"manual"}, extra_env={"x":"bad"})


def test_multiweek_backlog_uses_latest_and_occurrence_unique(setup):
    from datetime import datetime, timezone
    db, device, actor, owner, admin, task, grant, api, headers = setup
    now = datetime(2026, 6, 22, 8, 0, 5, tzinfo=timezone.utc)
    task.trigger = json.dumps({"kind":"weekly", "timezone":"UTC", "time":"08:00", "weekdays":[0], "misfire":"skip"})
    task.next_fire_at = now - timedelta(weeks=20)
    db.commit()
    assert s.dispatch_due_tasks(db, now) == 1
    execution = db.query(TaskExecution).one()
    assert s.aware(execution.scheduled_for) == now.replace(second=0)
    assert execution.state == "queued"
    assert s.dispatch_due_tasks(db, now) == 0
    assert s.occurrence(db, task, scheduled_for=execution.scheduled_for).id == execution.id
    assert db.query(Run).count() == 1


@pytest.mark.parametrize("operation", ["claim", "start", "manual", "import"])
def test_concurrent_cas_and_dedupe(setup, fresh_db, operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    db, device, actor, owner, admin, task, grant, api, headers = setup
    factory, _ = fresh_db
    execution = enqueue(db, task)
    attempt = str(uuid4())
    if operation == "start":
        s.claim(db, device, execution, attempt)
    execution_id, device_id, task_id = execution.id, device.id, task.id
    request_id = uuid4()
    timestamp = s.now_utc()
    import_req = LocalRunImportRequest(device_id=device_id, request_id=request_id,
                                      script_id=task.script_id, script_version=1, status="success",
                                      started_at=timestamp, finished_at=timestamp)
    owner_id = owner.id
    barrier = Barrier(2)
    def worker(index):
        with factory() as session:
            local_device = session.get(TaskDevice, device_id)
            local_execution = session.get(TaskExecution, execution_id)
            local_task = session.get(ScheduledTask, task_id)
            barrier.wait(timeout=10)
            try:
                if operation == "claim":
                    return s.claim(session, local_device, local_execution, str(uuid4()))["state"]
                if operation == "start":
                    return s.start(session, local_device, local_execution, attempt)["can_start"]
                if operation == "import":
                    return s.import_local(session, session.get(User, owner_id), "s" * 32, import_req)["id"]
                return s.task_action(session, local_task, TaskAction(action="run", request_id=request_id))["id"]
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    if operation == "claim":
        assert sorted(map(str, results)) == ["409", "claimed"]
    elif operation == "start":
        assert sorted(results) == [False, True]
    else:
        assert results[0] == results[1]
        model = LocalRunImport if operation == "import" else TaskExecution
        assert db.query(model).filter_by(request_id=str(request_id)).count() == 1


def test_cancel_wins_against_stale_start_session(setup, fresh_db):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    attempt = str(uuid4())
    s.claim(db, device, execution, attempt)
    factory, _ = fresh_db
    with factory() as stale:
        stale_device = stale.get(TaskDevice, device.id)
        stale_execution = stale.get(TaskExecution, execution.id)
        s.cancel_execution(db, execution)
        db.commit()
        assert not s.start(stale, stale_device, stale_execution, attempt)["can_start"]
        assert stale_execution.state == "cancel_requested"


def test_weekly_dst_gap_does_not_use_old_backlog(setup):
    from datetime import datetime, timezone
    db, device, actor, owner, admin, task, grant, api, headers = setup
    now = datetime(2026, 3, 14, 12, tzinfo=timezone.utc)
    task.trigger = json.dumps({"kind":"weekly", "timezone":"America/New_York", "time":"02:30", "weekdays":[6]})
    task.next_fire_at = now - timedelta(weeks=20)
    db.commit()
    assert s.dispatch_due_tasks(db, now) == 1
    execution = db.query(TaskExecution).one()
    # 3 月 8 日墙上时刻不存在；最近发生项距当前 13 天，旧 9 天窗口会漏掉。
    assert s.aware(execution.scheduled_for) == datetime(2026, 3, 1, 7, 30, tzinfo=timezone.utc)
    assert execution.state == "skipped"


def test_pending_revocation_does_not_leak_payload(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    s.claim(db, device, execution, str(uuid4()))
    actor.groups = []
    db.commit()
    response = api.get(f"/api/task-devices/{device.id}/pending", headers=headers())
    assert response.status_code == 200
    assert response.json()[0]["state"] == "cancel_requested"
    assert "params" not in response.json()[0]


@pytest.mark.parametrize('stored', [None, 'null', '[]', '{invalid'])
def test_invalid_fixed_version_config_is_not_silently_empty(setup, stored):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    db.query(ScriptVersion).filter_by(script_id=task.script_id, version=1).one().config_json = stored
    db.commit()
    with pytest.raises(HTTPException) as error:
        enqueue(db, task)
    assert error.value.status_code == 409
    assert db.query(TaskExecution).count() == 0


def test_queued_schedule_rechecks_misfire_window_at_claim(setup, monkeypatch):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    now = s.now_utc()
    task.trigger = json.dumps({'kind': 'daily', 'timezone': 'UTC', 'time': '09:00', 'misfire': 'skip'})
    execution = s.occurrence(db, task, scheduled_for=now)
    db.commit()
    monkeypatch.setattr(s, 'now_utc', lambda: now + timedelta(seconds=31))
    with pytest.raises(HTTPException, match='领取已过期'):
        s.claim(db, device, execution, str(uuid4()))
    assert db.get(TaskDevice, device.id).active_execution_id is None
    assert execution.state == 'cancelled'


def test_manual_run_of_paused_task_is_rejected_before_enqueue(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    s.task_action(db, task, TaskAction(action='pause'))
    with pytest.raises(HTTPException, match='已暂停'):
        enqueue(db, task)
    assert db.query(TaskExecution).count() == 0


def test_current_cancel_is_not_hidden_behind_a_full_pending_page(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    for _ in range(100):
        s.occurrence(db, task, request_id=str(uuid4()))
    current = s.occurrence(db, task, request_id=str(uuid4()))
    db.commit()
    s.claim(db, device, current, str(uuid4()))
    s.cancel_execution(db, current)
    db.commit()
    response = api.get(f'/api/task-devices/{device.id}/pending', headers=headers())
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 100
    assert rows[0]['id'] == current.id
    assert rows[0]['state'] == 'cancel_requested'


def test_task_controls_bound_raw_json_and_do_not_cache_parameters(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    response = api.post('/api/tasks', content=b'{' + b' ' * (512 * 1024), headers={**headers(actor), 'Content-Type': 'application/json'})
    assert response.status_code == 413  # Before attempting to decode malformed oversized JSON.
    response = api.get('/api/tasks', headers=headers(actor))
    assert response.headers['Cache-Control'] == 'no-store'


def test_run_detail_exposes_managed_cancel_target_and_audit_has_no_params(setup):
    from app.models import AuditLog
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    response = api.get(f'/api/runs/{execution.run_id}', headers=headers(actor))
    assert response.status_code == 200
    assert response.json()['task_execution_id'] == execution.id
    response = api.post(f'/api/tasks/executions/{execution.id}/cancel', headers=headers(actor))
    assert response.status_code == 200
    db.expire_all()
    audits = db.query(AuditLog).filter_by(action='cancel_task_execution').all()
    assert len(audits) == 1
    assert audits[0].user_id == actor.id
    assert audits[0].detail is None


def test_pending_prunes_expired_queue_before_a_device_creates_attempts(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    db.get(Run, execution.run_id).created_at = s.now_utc() - timedelta(seconds=301)
    db.commit()
    response = api.get(f'/api/task-devices/{device.id}/pending', headers=headers(owner, True))
    assert response.status_code == 200
    assert response.json() == []
    db.expire_all()
    assert execution.state == 'cancelled' and execution.stopped
    assert execution.attempt_id is None


def test_legacy_large_log_and_byte_offset_remain_compatible(setup, monkeypatch, tmp_path):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    monkeypatch.setattr(runs, 'LOGS_DIR', str(tmp_path / 'legacy-logs'))
    run = Run(script_id=task.script_id, script_version=1, user_id=actor.id, status='running', params='{}')
    db.add(run)
    db.commit()
    content = '合成日志\n' * 100000
    expected = len(content.encode('utf-8'))
    assert expected > 1024 * 1024
    route = f'/api/runs/{run.id}/log/chunk'
    for _ in range(2):
        response = api.post(route, json={'offset': 0, 'content': content}, headers=headers(actor))
        assert response.status_code == 200
        assert response.json()['offset'] == expected
    response = api.post(route, json={'offset': 0, 'content': 'conflicting'}, headers=headers(actor))
    assert response.status_code == 409
    assert response.json()['detail']['offset'] == expected
    assert api.get(f'/api/runs/{run.id}/log', headers=headers(actor)).json()['log'] == content


def test_legacy_log_rejects_identity_before_parsing_body(setup, monkeypatch):
    from starlette.requests import Request
    db, device, actor, owner, admin, task, grant, api, headers = setup
    run = Run(script_id=task.script_id, script_version=1, user_id=actor.id, status='running', params='{}')
    db.add(run)
    db.commit()
    async def forbidden_body(self):
        pytest.fail('body must not be read before authentication and ownership checks')
    monkeypatch.setattr(Request, 'body', forbidden_body)
    route = f'/api/runs/{run.id}/log/chunk'
    assert api.post(route, content=b'invalid').status_code == 401
    assert api.post(route, content=b'invalid', headers=headers(owner)).status_code == 403


def test_legacy_pending_never_exposes_managed_rows(setup):
    db, device, actor, owner, admin, task, grant, api, headers = setup
    execution = enqueue(db, task)
    db.get(Run, execution.run_id).status = 'pending'  # Historical corruption must not poison old limit=1 polling.
    db.commit()
    response = api.get('/api/runs?status=pending&limit=1&mine_only=true', headers=headers(actor))
    assert response.status_code == 200 and response.json() == []
