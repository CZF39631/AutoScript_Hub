"""设备任务事务服务。所有状态转移使用数据库 CAS，不依赖进程内锁。"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.models import TaskDevice, DeviceGrant, ScheduledTask, TaskExecution, LocalRunImport, Run, User, ScriptVersion, AuditLog
from app.services.script_access import get_accessible_script_or_404
from app.services.diagnostic_policy import load_diagnostic_policy
from shared.script_contract import validate_params

TERMINAL = {"success", "failed", "cancelled", "skipped"}
ACTIVE = ("queued", "claimed", "running", "cancel_requested", "unknown")


def now_utc():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def fail(message, status=409):
    raise HTTPException(status, message)


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def audit_task(db, user_id, action, target_type, target_id):
    """与状态变更同事务保存审计；不记录秘密、参数和设备认证头。"""
    user = db.get(User, user_id)
    db.add(AuditLog(user_id=user_id, username=user.username if user else None,
                    action=action, target_type=target_type, target_id=target_id))


def device_auth(db, device_id, user, token):
    device = db.get(TaskDevice, device_id)
    if not device or user.status != "active" or user.is_deleted or device.user_id != user.id or not token or not hmac.compare_digest(device.secret_hash, digest(token)):
        fail("设备凭据无效", 403)
    return device


def device_public(device):
    return {key: getattr(device, key) for key in ("id", "device_uuid", "name", "user_id", "status")}


def register(db, req, user):
    device = db.query(TaskDevice).filter_by(device_uuid=str(req.device_uuid)).first()
    if device:
        device_auth(db, device.id, user, req.device_secret)
        device.name, device.agent_version = req.name, req.agent_version
        device.last_heartbeat, device.status = now_utc(), "online"
    else:
        device = TaskDevice(device_uuid=str(req.device_uuid), secret_hash=digest(req.device_secret), user_id=user.id, name=req.name, agent_version=req.agent_version)
        db.add(device)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("设备注册冲突，请凭原秘密重试")
    return device_public(device)


def version_access(db, user_id, script_id, version, params=None):
    user = db.get(User, user_id)
    if not user or user.status != "active" or user.is_deleted:
        fail("用户不可用", 403)
    get_accessible_script_or_404(db, user, script_id, require_active=True)
    row = db.query(ScriptVersion).filter_by(script_id=script_id, version=version).first()
    if not row:
        fail("固定脚本版本不存在", 404)
    try:
        config = json.loads(row.config_json)
        if not isinstance(config, dict) or not isinstance(config.get("params", []), list):
            raise ValueError("invalid version config")
    except (TypeError, ValueError):
        fail("固定版本配置不可用，请联系脚本维护者", 409)
    if params is not None:
        errors = validate_params(config.get("params", []), params, check_paths=False)
        if errors:
            fail("; ".join(errors), 422)
    return row


def authorization(db, task):
    device = db.get(TaskDevice, task.device_id)
    if not device:
        fail("设备不存在", 404)
    version_access(db, task.requester_id, task.script_id, task.script_version, json.loads(task.params))
    version_access(db, device.user_id, task.script_id, task.script_version)
    grant = db.query(DeviceGrant).filter_by(device_id=device.id, requester_id=task.requester_id, script_id=task.script_id, script_version=task.script_version, status="accepted").first()
    if not grant:
        fail("设备授权无效或已撤销", 403)
    # Serialize grant revocation with claim/start on databases with row locking too.
    if db.query(DeviceGrant).filter_by(id=grant.id, status="accepted").update({DeviceGrant.status: "accepted"}) != 1:
        fail("设备授权已撤销", 403)
    return device


def task_public(task):
    data = {k: getattr(task, k) for k in ("id", "name", "device_id", "script_id", "script_version", "timeout_seconds", "requires_desktop", "requires_browser", "enabled", "next_fire_at")}
    data.update(params=json.loads(task.params), trigger=json.loads(task.trigger))
    return data


def execution_public(db, execution, payload=False):
    task = db.get(ScheduledTask, execution.task_id)
    data = {k: getattr(execution, k) for k in ("id", "task_id", "run_id", "device_id", "state", "scheduled_for", "error_msg", "attempt_id")}
    data["task_name"] = task.name
    if payload:
        data.update({k: getattr(task, k) for k in ("script_id", "script_version", "timeout_seconds", "requires_desktop", "requires_browser")})
        data["params"] = json.loads(task.params)
    return data


def owned_task(db, task_id, user):
    task = db.get(ScheduledTask, task_id)
    if not task or (task.requester_id != user.id and user.role != "admin"):
        fail("任务不存在", 404)
    return task


def create_task(db, req, user):
    from shared.scheduling import validate_trigger, next_fire
    try:
        trigger = validate_trigger(req.trigger)
    except ValueError as exc:
        fail(str(exc), 422)
    task = ScheduledTask(**req.model_dump(exclude={"params", "trigger"}), requester_id=user.id, params=json.dumps(req.params), trigger=json.dumps(trigger))
    authorization(db, task)
    now = now_utc()
    task.next_fire_at = next_fire(trigger, now)
    if trigger["kind"] == "once":
        task.next_fire_at = datetime.fromisoformat(trigger["start_at"].replace("Z", "+00:00"))
    db.add(task)
    db.flush()
    audit_task(db, user.id, 'create_task', 'task', task.id)
    db.commit()
    return task_public(task)


def occurrence(db, task, scheduled_for=None, request_id=None, state="queued"):
    filters = dict(task_id=task.id, request_id=request_id) if request_id else dict(task_id=task.id, revision=task.revision, scheduled_for=scheduled_for)
    existing = db.query(TaskExecution).filter_by(**filters).first()
    if existing:
        return existing
    try:
        with db.begin_nested():
            run = Run(script_id=task.script_id, script_version=task.script_version, user_id=task.requester_id, params=task.params, status=state)
            if state in TERMINAL:
                run.finished_at = now_utc()
            db.add(run)
            db.flush()
            execution = TaskExecution(task_id=task.id, device_id=task.device_id, run_id=run.id, revision=task.revision, scheduled_for=scheduled_for, request_id=request_id, state=state, stopped=state in TERMINAL)
            db.add(execution)
            db.flush()
        return execution
    except IntegrityError:
        return db.query(TaskExecution).filter_by(**filters).one()


def cancel_execution(db, execution):
    if execution.stopped or execution.state in TERMINAL or execution.state == "cancel_requested":
        return
    old = execution.state
    target = "cancelled" if old == "queued" else "cancel_requested"
    if db.query(TaskExecution).filter_by(id=execution.id, state=old).update({TaskExecution.state: target, TaskExecution.stopped: target == "cancelled"}, synchronize_session=False) != 1:
        fail("执行状态已变化，请重试")
    run = db.get(Run, execution.run_id)
    run.status = target
    if target == "cancelled":
        run.finished_at = now_utc()
    db.flush()
    db.expire(execution)


def task_action(db, task, req, actor_id=None):
    from shared.scheduling import next_fire
    if task.is_deleted:
        fail("任务已删除")
    if req.action == "run":
        if not req.request_id:
            fail("手动执行必须提供 UUID request_id", 422)
        if not task.enabled:
            fail("任务已暂停，请核对设备状态并恢复后再运行")
        authorization(db, task)
        execution = occurrence(db, task, request_id=str(req.request_id))
        audit_task(db, actor_id or task.requester_id, 'run_task', 'task_execution', execution.id)
        db.commit()
        return execution_public(db, execution)
    task.enabled = req.action == "resume"
    if req.action == "resume":
        authorization(db, task)
        task.next_fire_at = next_fire(json.loads(task.trigger), now_utc())
    if req.action == "delete":
        task.is_deleted = True
    if req.action in ("pause", "delete"):
        for execution in db.query(TaskExecution).filter_by(task_id=task.id).filter(TaskExecution.state.in_(ACTIVE)).all():
            cancel_execution(db, execution)
    audit_task(db, actor_id or task.requester_id, 'task_' + req.action, 'task', task.id)
    db.commit()
    return task_public(task)


def get_execution(db, device, execution_id):
    execution = db.get(TaskExecution, execution_id)
    if not execution or execution.device_id != device.id:
        fail("执行不存在", 404)
    return execution


def queued_expired(db, execution, task, now=None):
    from shared.scheduling import due_occurrence
    now = now or now_utc()
    if execution.scheduled_for is not None:
        return not due_occurrence(json.loads(task.trigger), aware(execution.scheduled_for), now)
    return (now - aware(db.get(Run, execution.run_id).created_at)).total_seconds() > 300


def claim(db, device, execution, attempt):
    task = db.get(ScheduledTask, execution.task_id)
    try:
        authorization(db, task)
    except HTTPException:
        task.enabled = False
        cancel_execution(db, execution)
        db.commit()
        raise
    db.refresh(execution)
    db.refresh(task)
    if execution.attempt_id == attempt and execution.state in ACTIVE:
        db.commit()
        return execution_public(db, execution, True)
    if task.is_deleted or not task.enabled or execution.state != "queued":
        fail("任务不可领取")
    if queued_expired(db, execution, task):
        cancel_execution(db, execution)
        db.commit()
        fail("领取已过期")
    if db.query(TaskDevice).filter_by(id=device.id, active_execution_id=None).update({TaskDevice.active_execution_id: execution.id}, synchronize_session=False) != 1:
        fail("设备执行槽已占用")
    if db.query(TaskExecution).filter_by(id=execution.id, state="queued", attempt_id=None).update({TaskExecution.state: "claimed", TaskExecution.attempt_id: attempt, TaskExecution.claimed_at: now_utc()}, synchronize_session=False) != 1:
        db.rollback()
        fail("执行已被领取")
    db.get(Run, execution.run_id).status = "claimed"
    db.commit()
    db.refresh(execution)
    return execution_public(db, execution, True)


def start(db, device, execution, attempt):
    if execution.attempt_id != attempt:
        fail("attempt_id 不匹配")
    if execution.state != "claimed":
        return {"can_start": False, "state": execution.state}
    task = db.get(ScheduledTask, execution.task_id)
    try:
        authorization(db, task)
    except HTTPException:
        cancel_execution(db, execution)
        db.commit()
        return {"can_start": False, "state": execution.state}
    db.refresh(task)
    db.refresh(execution)
    db.refresh(device)
    if device.active_execution_id != execution.id:
        fail("设备执行槽不匹配")
    if not task.enabled or task.is_deleted or not execution.claimed_at or (now_utc() - aware(execution.claimed_at)).total_seconds() >= task.timeout_seconds:
        cancel_execution(db, execution)
        db.commit()
        return {"can_start": False, "state": execution.state}
    changed = db.query(TaskExecution).filter_by(id=execution.id, state="claimed", attempt_id=attempt).filter(TaskExecution.claimed_at > now_utc() - timedelta(seconds=task.timeout_seconds)).update({TaskExecution.state: "running"}, synchronize_session=False)
    if changed:
        run = db.get(Run, execution.run_id)
        run.status, run.started_at = "running", now_utc()
    db.commit()
    db.refresh(execution)
    return {"can_start": changed == 1, "state": execution.state}


def save_output(db, run, req):
    policy = load_diagnostic_policy(db)
    secrets = policy.secrets(json.loads(run.params or "{}"))
    error = policy.text(req.error_msg, "summary", secrets)
    run.error_msg = error.encode("utf-8")[:4096].decode("utf-8", errors="ignore") if error else error
    run.result_files = json.dumps(policy.params(req.result_files, secrets), ensure_ascii=False) if req.result_files is not None else None
    if run.result_files and len(run.result_files.encode("utf-8")) > 65536:
        fail("结果文件列表超过 64 KiB", 422)
    if req.log_tail is not None:
        from app.config import LOGS_DIR
        path = Path(LOGS_DIR) / (str(run.id) + ".log")
        path.parent.mkdir(parents=True, exist_ok=True)
        content = policy.text(req.log_tail, "logs", secrets).encode("utf-8")[:65536].decode("utf-8", errors="ignore")
        path.write_bytes(content.encode("utf-8"))
        run.log_path = str(path.resolve())


def report(db, device, execution, req):
    if execution.attempt_id != str(req.attempt_id):
        fail("attempt_id 不匹配")
    if execution.state in TERMINAL or (execution.state == "unknown" and execution.stopped):
        if execution.state != req.state:
            fail("不能覆盖已确认终态")
        return execution_public(db, execution)
    old = execution.state
    if old not in ("claimed", "running", "cancel_requested", "unknown"):
        fail("执行尚未领取")
    if db.query(TaskExecution).filter_by(id=execution.id, state=old, stopped=False).update({TaskExecution.state: req.state, TaskExecution.stopped: True}, synchronize_session=False) != 1:
        fail("执行状态已变化")
    run = db.get(Run, execution.run_id)
    run.status, run.finished_at = req.state, now_utc()
    if run.started_at:
        run.duration_sec = max(0, int((run.finished_at - aware(run.started_at)).total_seconds()))
    save_output(db, run, req)
    db.query(TaskExecution).filter_by(id=execution.id).update({TaskExecution.error_msg: run.error_msg}, synchronize_session=False)
    db.query(TaskDevice).filter_by(id=device.id, active_execution_id=execution.id).update({TaskDevice.active_execution_id: None}, synchronize_session=False)
    if req.state == "unknown":
        db.get(ScheduledTask, execution.task_id).enabled = False
    db.commit()
    db.refresh(execution)
    return execution_public(db, execution)


def dispatch_due_tasks(db, now):
    """最多处理 100 个任务；周期仅计算最近发生项；调用方每次传新 Session。"""
    from shared.scheduling import next_fire, latest_fire, due_occurrence
    tasks = db.query(ScheduledTask).filter(ScheduledTask.enabled == True, ScheduledTask.is_deleted == False, ScheduledTask.next_fire_at <= now).order_by(ScheduledTask.next_fire_at).limit(100).all()
    count = 0
    for task in tasks:
        trigger = json.loads(task.trigger)
        scheduled = aware(task.next_fire_at)
        if trigger["kind"] in ("daily", "weekly"):
            candidate = latest_fire(trigger, now)
            if candidate is not None and candidate >= scheduled:
                scheduled = candidate
        old_next = task.next_fire_at
        upcoming = next_fire(trigger, now)
        if db.query(ScheduledTask).filter_by(id=task.id, enabled=True, is_deleted=False, next_fire_at=old_next).update({ScheduledTask.next_fire_at: upcoming}, synchronize_session=False) != 1:
            continue
        try:
            authorization(db, task)
            state = "queued" if due_occurrence(trigger, scheduled, now) else "skipped"
        except HTTPException:
            state = "skipped"
            task.enabled = False
        occurrence(db, task, scheduled_for=scheduled, state=state)
        count += 1
    db.commit()
    return count


def mark_stale_tasks(db, now):
    cutoff = now - timedelta(seconds=90)
    devices = db.query(TaskDevice).filter(TaskDevice.last_heartbeat < cutoff, TaskDevice.status != "offline").limit(100).all()
    count = 0
    for device in devices:
        changed = db.query(TaskDevice).filter(TaskDevice.id == device.id, TaskDevice.last_heartbeat < cutoff).update({TaskDevice.status: "offline"}, synchronize_session=False)
        if not changed:
            continue
        executions = db.query(TaskExecution).filter_by(device_id=device.id).filter(TaskExecution.state.in_(("claimed", "running", "cancel_requested"))).limit(100).all()
        for execution in executions:
            if db.query(TaskExecution).filter_by(id=execution.id, state=execution.state, stopped=False).update({TaskExecution.state: "unknown"}, synchronize_session=False):
                db.get(Run, execution.run_id).status = "unknown"
                db.get(ScheduledTask, execution.task_id).enabled = False
                count += 1
    db.commit()
    return count


def import_local(db, user, token, req):
    device = device_auth(db, req.device_id, user, token)
    payload = req.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    if len(encoded.encode()) > 131072 or (req.log_tail and len(req.log_tail.encode()) > 65536):
        fail("导入数据过大", 422)
    fingerprint = digest(encoded)
    previous = db.query(LocalRunImport).filter_by(device_id=device.id, request_id=str(req.request_id)).first()
    if previous:
        if previous.payload_hash != fingerprint:
            fail("request_id 已用于不同导入内容")
        return {"id": previous.run_id, "run_id": previous.run_id, "status": req.status, "imported": False}
    version_access(db, user.id, req.script_id, req.script_version, req.params)
    if req.finished_at < req.started_at:
        fail("结束时间不能早于开始时间", 422)
    try:
        with db.begin_nested():
            run = Run(script_id=req.script_id, script_version=req.script_version, user_id=user.id, status=req.status, params=json.dumps(req.params), started_at=req.started_at, finished_at=req.finished_at, duration_sec=int((req.finished_at-req.started_at).total_seconds()))
            db.add(run)
            db.flush()
            db.add(LocalRunImport(device_id=device.id, request_id=str(req.request_id), payload_hash=fingerprint, run_id=run.id))
            db.flush()
            save_output(db, run, req)
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.query(LocalRunImport).filter_by(device_id=device.id, request_id=str(req.request_id)).first()
        if not previous:
            raise  # 非幂等键冲突不可无限递归或隐藏数据库错误。
        if previous.payload_hash != fingerprint:
            fail("request_id 已用于不同导入内容")
        return {"id": previous.run_id, "run_id": previous.run_id, "status": req.status, "imported": False}
    return {"id": run.id, "run_id": run.id, "status": run.status, "imported": True}
