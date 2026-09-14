"""固定版本远程任务；设备同意不能由远程用户身份替代。"""
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, case
from sqlalchemy.exc import IntegrityError
from app.auth import get_current_user
from app.database import get_db
from app.models import User, TaskDevice, DeviceGrant, ScheduledTask, TaskExecution
from app.schemas import DeviceRegister, GrantRequest, GrantDecision, TaskCreate, TaskAction, TaskAttempt, TaskReport
from app.services import task_service as service

from app.request_limits import BoundedJsonRoute

router = APIRouter(tags=["tasks"], route_class=BoundedJsonRoute)


def authenticated_device(device_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), x_device_token: str | None = Header(default=None)):
    return service.device_auth(db, device_id, current_user, x_device_token)


def grant_public(db, grant):
    data = {key: getattr(grant, key) for key in ("id", "device_id", "requester_id", "script_id", "script_version", "status")}
    user = db.get(User, grant.requester_id)
    data["requester_name"] = user.display_name if user else ""
    return data


@router.post("/api/task-devices/register")
def register(req: DeviceRegister, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.register(db, req, user)


@router.get("/api/task-devices")
def devices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(TaskDevice)
    if user.role != "admin":
        query = query.filter(or_(TaskDevice.user_id == user.id, TaskDevice.id.in_(db.query(DeviceGrant.device_id).filter_by(requester_id=user.id))))
    return [service.device_public(d) for d in query.order_by(TaskDevice.id).limit(200).all()]


@router.post("/api/task-devices/{device_id}/grants")
def request_grant(device_id: int, req: GrantRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    device = db.get(TaskDevice, device_id)
    if not device:
        service.fail("设备不存在", 404)
    service.version_access(db, user.id, req.script_id, req.script_version)
    service.version_access(db, device.user_id, req.script_id, req.script_version)
    keys = dict(device_id=device_id, requester_id=user.id, **req.model_dump())
    grant = db.query(DeviceGrant).filter_by(**keys).first()
    if not grant:
        grant = DeviceGrant(**keys)
        db.add(grant)
        try:
            db.flush()
            service.audit_task(db, user.id, 'request_device_grant', 'device_grant', grant.id)
            db.commit()
        except IntegrityError:
            db.rollback()
            grant = db.query(DeviceGrant).filter_by(**keys).one()
    # A remote retry never restores a rejected/revoked grant.
    return grant_public(db, grant)


@router.get("/api/tasks/grants")
def grants(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(DeviceGrant)
    if user.role != "admin":
        query = query.filter_by(requester_id=user.id)
    return [grant_public(db, g) for g in query.order_by(DeviceGrant.id.desc()).limit(200).all()]


@router.get("/api/task-devices/{device_id}/grants")
def device_grants(device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    return [grant_public(db, g) for g in db.query(DeviceGrant).filter_by(device_id=device.id).order_by(DeviceGrant.id).limit(200).all()]


@router.post("/api/task-devices/{device_id}/grants/{grant_id}/decision")
def decision(grant_id: int, req: GrantDecision, device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    grant = db.query(DeviceGrant).filter_by(id=grant_id, device_id=device.id).first()
    if not grant:
        service.fail("授权不存在", 404)
    target = {"accept": "accepted", "reject": "rejected", "revoke": "revoked"}[req.decision]
    if target == "accepted":
        service.version_access(db, grant.requester_id, grant.script_id, grant.script_version)
        service.version_access(db, device.user_id, grant.script_id, grant.script_version)
    if db.query(DeviceGrant).filter_by(id=grant.id, status=grant.status).update({DeviceGrant.status: target}, synchronize_session=False) != 1:
        service.fail("授权状态已变化，请重试")
    if target != "accepted":
        tasks = db.query(ScheduledTask).filter_by(device_id=device.id, requester_id=grant.requester_id, script_id=grant.script_id, script_version=grant.script_version).all()
        for task in tasks:
            task.enabled = False
            for execution in db.query(TaskExecution).filter_by(task_id=task.id).filter(TaskExecution.state.in_(service.ACTIVE)).all():
                service.cancel_execution(db, execution)
    service.audit_task(db, device.user_id, 'device_grant_' + req.decision, 'device_grant', grant.id)
    db.commit()
    db.refresh(grant)
    return grant_public(db, grant)


@router.post("/api/task-devices/{device_id}/heartbeat")
def heartbeat(device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    device.last_heartbeat, device.status = service.now_utc(), "online"
    db.commit()
    return {"status": "ok", "device_id": device.id}


@router.post("/api/tasks")
def create(req: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.create_task(db, req, user)


@router.get("/api/tasks")
def tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ScheduledTask).filter_by(is_deleted=False)
    if user.role != "admin":
        query = query.filter_by(requester_id=user.id)
    return [service.task_public(t) for t in query.order_by(ScheduledTask.id.desc()).limit(200).all()]


@router.get("/api/tasks/executions")
def executions(limit: int = Query(100, ge=1, le=200), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(TaskExecution).join(ScheduledTask)
    if user.role != "admin":
        query = query.filter(ScheduledTask.requester_id == user.id)
    return [service.execution_public(db, e) for e in query.order_by(TaskExecution.id.desc()).limit(limit).all()]


@router.post("/api/tasks/{task_id}/action")
def action(task_id: int, req: TaskAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.task_action(db, service.owned_task(db, task_id, user), req, actor_id=user.id)


@router.post("/api/tasks/executions/{execution_id}/cancel")
def cancel(execution_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    execution = db.get(TaskExecution, execution_id)
    if not execution:
        service.fail("执行不存在", 404)
    service.owned_task(db, execution.task_id, user)
    service.cancel_execution(db, execution)
    service.audit_task(db, user.id, 'cancel_task_execution', 'task_execution', execution.id)
    db.commit()
    return service.execution_public(db, execution)


@router.get("/api/task-devices/{device_id}/pending")
def pending(device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    query = db.query(TaskExecution).filter_by(device_id=device.id, stopped=False).filter(TaskExecution.state.in_(service.ACTIVE))
    result = []
    # 大量排队项不能把当前执行的取消指令挤出有界响应。
    priority = case((TaskExecution.id == device.active_execution_id, 0), (TaskExecution.state != 'queued', 1), else_=2)
    for execution in query.order_by(priority, TaskExecution.id).limit(100).all():
        task = db.get(ScheduledTask, execution.task_id)
        if execution.state == 'queued' and service.queued_expired(db, execution, task):
            service.cancel_execution(db, execution)
            continue
        try:
            service.authorization(db, task)
        except service.HTTPException:
            task.enabled = False
            service.cancel_execution(db, execution)
            # 撤权后只发停止/对账元数据，不再下发脚本参数。
            if not execution.stopped:
                result.append(service.execution_public(db, execution))
        else:
            result.append(service.execution_public(db, execution, True))
    db.commit()
    return result


@router.post("/api/task-devices/{device_id}/executions/{execution_id}/claim")
def claim(execution_id: int, req: TaskAttempt, device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    return service.claim(db, device, service.get_execution(db, device, execution_id), str(req.attempt_id))


@router.post("/api/task-devices/{device_id}/executions/{execution_id}/start")
def start(execution_id: int, req: TaskAttempt, device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    return service.start(db, device, service.get_execution(db, device, execution_id), str(req.attempt_id))


@router.post("/api/task-devices/{device_id}/executions/{execution_id}/report")
def report(execution_id: int, req: TaskReport, device: TaskDevice = Depends(authenticated_device), db: Session = Depends(get_db)):
    return service.report(db, device, service.get_execution(db, device, execution_id), req)
