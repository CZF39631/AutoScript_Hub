"""Admin-only managed Agent dispatch and fixed-interval schedule APIs."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import Agent, Environment, ManagedSchedule, Run, Script, User
from app.routers.agents import AgentItem
from app.routers.runs import _enrich_run
from app.schemas import RunBrief
from app.services.agent_thumbnails import thumbnail_path
from app.services.audit import write_audit
from app.services.run_dispatch import create_validated_run, validate_run_request
from app.services.script_access import restrict_script_query
from app.services.schedule_time import (
    next_schedule_time, utc_naive, validate_cron_expression, validate_timezone,
)

router = APIRouter(prefix="/api/admin", tags=["managed-agents"])


class ManagedAgentItem(AgentItem):
    thumbnail_updated_at: Optional[datetime] = None
    thumbnail_size: Optional[int] = None
    running_run_id: Optional[int] = None
    running_dispatch_type: Optional[str] = None


class ManagedRunCreate(BaseModel):
    script_id: int
    params: Dict[str, Any] = Field(default_factory=dict)
    environment_id: Optional[int] = None
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)


class ManagedAgentUpdate(BaseModel):
    enabled: bool


class ManagedScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    agent_id: int
    script_id: int
    params: Dict[str, Any] = Field(default_factory=dict)
    environment_id: Optional[int] = None
    schedule_type: Literal["interval", "cron"] = "interval"
    interval_seconds: Optional[int] = Field(default=None, ge=60, le=31536000)
    cron_expression: Optional[str] = Field(default=None, max_length=100)
    timezone: str = Field(default="UTC", max_length=100)
    expires_after_seconds: int = Field(default=3600, ge=60, le=604800)
    enabled: bool = True
    next_run_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_rule(self):
        if self.schedule_type == "interval":
            if self.interval_seconds is None or self.cron_expression is not None:
                raise ValueError("interval 调度仅需提供 interval_seconds")
        else:
            if self.interval_seconds is not None:
                raise ValueError("cron 调度不可提供 interval_seconds")
            self.cron_expression = validate_cron_expression(self.cron_expression or "")
        self.timezone = validate_timezone(self.timezone)
        return self


class ManagedScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    agent_id: Optional[int] = None
    script_id: Optional[int] = None
    params: Optional[Dict[str, Any]] = None
    environment_id: Optional[int] = None
    schedule_type: Optional[Literal["interval", "cron"]] = None
    interval_seconds: Optional[int] = Field(default=None, ge=60, le=31536000)
    cron_expression: Optional[str] = Field(default=None, max_length=100)
    timezone: Optional[str] = Field(default=None, max_length=100)
    expires_after_seconds: Optional[int] = Field(default=None, ge=60, le=604800)
    enabled: Optional[bool] = None
    next_run_at: Optional[datetime] = None

    @model_validator(mode="after")
    def reject_null_for_non_nullable_fields(self):
        non_nullable = {
            "name", "agent_id", "script_id", "params", "schedule_type",
            "expires_after_seconds", "enabled", "next_run_at", "timezone",
        }
        invalid = sorted(
            field for field in self.model_fields_set
            if field in non_nullable and getattr(self, field) is None
        )
        if invalid:
            raise ValueError("以下字段不可为 null: {}".format(", ".join(invalid)))
        return self


class ManagedScheduleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    agent_id: int
    script_id: int
    params: Dict[str, Any]
    environment_id: Optional[int] = None
    schedule_type: Literal["interval", "cron"]
    interval_seconds: Optional[int] = None
    cron_expression: Optional[str] = None
    timezone: str
    expires_after_seconds: int
    enabled: bool
    next_run_at: datetime
    last_run_at: Optional[datetime] = None
    created_by: int
    updated_by: int
    created_at: datetime
    updated_at: datetime


def _utc_naive(value: datetime) -> datetime:
    """Backward-compatible alias for UTC-naive database storage."""
    return utc_naive(value)


def _managed_agent_or_404(db: Session, agent_id: int, *, require_enabled: bool = False) -> Agent:
    query = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.mode == "managed",
        Agent.is_deleted == False,
    )
    if require_enabled:
        query = query.filter(Agent.enabled == True)
    agent = query.first()
    if not agent:
        raise HTTPException(status_code=404, detail="托管 Agent 不存在或不可用")
    return agent


def _schedule_or_404(db: Session, schedule_id: int) -> ManagedSchedule:
    schedule = db.query(ManagedSchedule).filter(
        ManagedSchedule.id == schedule_id,
        ManagedSchedule.is_deleted == False,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="托管计划不存在")
    return schedule


def _schedule_item(schedule: ManagedSchedule) -> ManagedScheduleItem:
    try:
        params = json.loads(schedule.params or "{}")
    except (TypeError, json.JSONDecodeError):
        params = {}
    return ManagedScheduleItem(
        id=schedule.id,
        name=schedule.name,
        agent_id=schedule.agent_id,
        script_id=schedule.script_id,
        params=params,
        environment_id=schedule.environment_id,
        schedule_type=schedule.schedule_type,
        interval_seconds=schedule.interval_seconds,
        cron_expression=schedule.cron_expression,
        timezone=schedule.timezone,
        expires_after_seconds=schedule.expires_after_seconds,
        enabled=schedule.enabled,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        created_by=schedule.created_by,
        updated_by=schedule.updated_by,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _create_schedule_run(
    db: Session,
    schedule: ManagedSchedule,
    actor_id: int,
    *,
    now: datetime,
    scheduled_for: datetime,
) -> Run:
    active = db.query(Run).filter(
        Run.schedule_id == schedule.id,
        Run.status.in_(["pending", "running"]),
        Run.is_deleted == False,
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="该计划已有待执行或执行中的任务")
    agent = _managed_agent_or_404(db, schedule.agent_id, require_enabled=True)
    owner = db.query(User).filter(
        User.id == agent.user_id,
        User.status == "active",
        User.is_deleted == False,
    ).first()
    if not owner:
        raise HTTPException(status_code=409, detail="Agent 所属用户不可用")
    return create_validated_run(
        db,
        run_user=owner,
        script_id=schedule.script_id,
        params=json.loads(schedule.params or "{}"),
        environment_id=schedule.environment_id,
        requested_by=actor_id,
        dispatch_type="managed_schedule",
        target_agent_id=agent.id,
        schedule_id=schedule.id,
        scheduled_for=scheduled_for,
        expires_at=scheduled_for + timedelta(seconds=schedule.expires_after_seconds),
        commit=False,
    )


@router.get("/managed-agents", response_model=List[ManagedAgentItem])
def list_managed_agents(
    enabled: Optional[bool] = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    query = db.query(Agent).filter(Agent.mode == "managed", Agent.is_deleted == False)
    if enabled is not None:
        query = query.filter(Agent.enabled == enabled)
    agents = query.order_by(Agent.enabled.desc(), Agent.last_heartbeat.desc()).all()
    agent_ids = [agent.id for agent in agents]
    running_by_agent = {}
    if agent_ids:
        running = db.query(Run).filter(
            Run.status == "running",
            Run.is_deleted == False,
            or_(Run.target_agent_id.in_(agent_ids), Run.agent_id.in_(agent_ids)),
        ).order_by(Run.created_at.asc()).all()
        for run in running:
            device_id = run.agent_id or run.target_agent_id
            if device_id in agent_ids and device_id not in running_by_agent:
                running_by_agent[device_id] = run
    return [
        ManagedAgentItem.model_validate(agent).model_copy(
            update={
                "running_run_id": running_by_agent.get(agent.id).id
                if running_by_agent.get(agent.id) else None,
                "running_dispatch_type": running_by_agent.get(agent.id).dispatch_type
                if running_by_agent.get(agent.id) else None,
            }
        )
        for agent in agents
    ]


@router.get("/managed-agents/{agent_id}/thumbnail")
def get_managed_agent_thumbnail(
    agent_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agent = _managed_agent_or_404(db, agent_id)
    path = thumbnail_path(agent.id)
    if agent.thumbnail_updated_at is None or agent.thumbnail_size is None or not path.is_file():
        raise HTTPException(status_code=404, detail="缩略图不存在")
    return FileResponse(
        path=str(path),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/managed-agents/{agent_id}/options")
def get_managed_agent_options(
    agent_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Return resources the target device owner can actually execute."""
    agent = _managed_agent_or_404(db, agent_id)
    owner = db.query(User).filter(
        User.id == agent.user_id,
        User.status == "active",
        User.is_deleted == False,
    ).first()
    if not owner:
        raise HTTPException(status_code=409, detail="Agent 所属用户不可用")
    scripts = restrict_script_query(
        db.query(Script).filter(Script.is_deleted == False, Script.status == "active"),
        owner,
    ).order_by(Script.name.asc()).all()
    environments = db.query(Environment).filter(
        Environment.user_id == owner.id,
    ).order_by(Environment.is_default.desc(), Environment.created_at.asc()).all()
    return {
        "owner": {"id": owner.id, "display_name": owner.display_name},
        "scripts": [{"id": item.id, "name": item.name, "status": item.status} for item in scripts],
        "environments": [
            {"id": item.id, "name": item.name, "is_default": item.is_default}
            for item in environments
        ],
    }


@router.patch("/managed-agents/{agent_id}", response_model=AgentItem)
def update_managed_agent(
    agent_id: int,
    req: ManagedAgentUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agent = _managed_agent_or_404(db, agent_id)
    agent.enabled = req.enabled
    if not req.enabled:
        agent.status = "offline"
        now = datetime.now(timezone.utc)
        db.query(Run).filter(
            Run.target_agent_id == agent.id,
            Run.status == "pending",
            Run.is_deleted == False,
        ).update(
            {
                Run.status: "cancelled",
                Run.finished_at: now,
                Run.error_msg: "托管 Agent 已被禁用，任务已取消",
            },
            synchronize_session=False,
        )
        db.query(Run).filter(
            or_(Run.target_agent_id == agent.id, Run.agent_id == agent.id),
            Run.status == "running",
            Run.is_deleted == False,
        ).update(
            {
                Run.status: "failed",
                Run.finished_at: now,
                Run.error_msg: "托管 Agent 已被禁用，任务执行失败",
            },
            synchronize_session=False,
        )
    db.commit()
    db.refresh(agent)
    write_audit(
        current_user.id,
        current_user.username,
        "managed_agent.update",
        target_type="agent",
        target_id=agent.id,
        detail="enabled={}".format(req.enabled),
    )
    return agent


@router.post("/managed-agents/{agent_id}/runs", response_model=RunBrief)
def dispatch_managed_run(
    agent_id: int,
    req: ManagedRunCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agent = _managed_agent_or_404(db, agent_id, require_enabled=True)
    owner = db.query(User).filter(
        User.id == agent.user_id,
        User.status == "active",
        User.is_deleted == False,
    ).first()
    if not owner:
        raise HTTPException(status_code=409, detail="Agent 所属用户不可用")
    running = db.query(Run).filter(
        Run.status == "running",
        Run.is_deleted == False,
        or_(Run.target_agent_id == agent.id, Run.agent_id == agent.id),
    ).first()
    if running:
        raise HTTPException(
            status_code=409,
            detail="设备正在执行任务 #{}，暂时不能下发临时任务".format(running.id),
        )
    now = datetime.now(timezone.utc)
    run = create_validated_run(
        db,
        run_user=owner,
        script_id=req.script_id,
        params=req.params,
        environment_id=req.environment_id,
        requested_by=current_user.id,
        dispatch_type="managed_manual",
        target_agent_id=agent.id,
        scheduled_for=now,
        expires_at=now + timedelta(seconds=req.expires_in_seconds),
    )
    write_audit(
        current_user.id,
        current_user.username,
        "managed_run.dispatch",
        target_type="run",
        target_id=run.id,
        detail="agent={} script={}".format(agent.id, req.script_id),
    )
    return _enrich_run(run, db)


@router.get("/managed-schedules", response_model=List[ManagedScheduleItem])
def list_managed_schedules(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    schedules = db.query(ManagedSchedule).filter(
        ManagedSchedule.is_deleted == False
    ).order_by(ManagedSchedule.created_at.desc()).all()
    return [_schedule_item(item) for item in schedules]


@router.post("/managed-schedules", response_model=ManagedScheduleItem)
def create_managed_schedule(
    req: ManagedScheduleCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agent = _managed_agent_or_404(db, req.agent_id)
    owner = db.query(User).filter(User.id == agent.user_id, User.is_deleted == False).first()
    if not owner:
        raise HTTPException(status_code=409, detail="Agent 所属用户不可用")
    validate_run_request(db, owner, req.script_id, req.params, req.environment_id)
    now = datetime.now(timezone.utc)
    next_run_at = req.next_run_at if req.schedule_type == "interval" else None
    next_run_at = next_run_at or next_schedule_time(
        schedule_type=req.schedule_type, after=now,
        interval_seconds=req.interval_seconds, cron_expression=req.cron_expression,
        timezone_name=req.timezone,
    )
    schedule = ManagedSchedule(
        name=req.name.strip(),
        agent_id=agent.id,
        script_id=req.script_id,
        params=json.dumps(req.params, ensure_ascii=False),
        environment_id=req.environment_id,
        schedule_type=req.schedule_type,
        interval_seconds=req.interval_seconds,
        cron_expression=req.cron_expression,
        timezone=req.timezone,
        expires_after_seconds=req.expires_after_seconds,
        enabled=req.enabled,
        next_run_at=_utc_naive(next_run_at),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    write_audit(
        current_user.id,
        current_user.username,
        "managed_schedule.create",
        target_type="managed_schedule",
        target_id=schedule.id,
        detail="agent={} script={} type={}".format(agent.id, req.script_id, req.schedule_type),
    )
    return _schedule_item(schedule)


@router.get("/managed-schedules/{schedule_id}", response_model=ManagedScheduleItem)
def get_managed_schedule(
    schedule_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return _schedule_item(_schedule_or_404(db, schedule_id))


@router.patch("/managed-schedules/{schedule_id}", response_model=ManagedScheduleItem)
def update_managed_schedule(
    schedule_id: int,
    req: ManagedScheduleUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    schedule = _schedule_or_404(db, schedule_id)
    values = req.model_dump(exclude_unset=True)
    agent_id = values.get("agent_id", schedule.agent_id)
    script_id = values.get("script_id", schedule.script_id)
    params = values.get("params", json.loads(schedule.params or "{}"))
    environment_id = values.get("environment_id", schedule.environment_id)
    agent = _managed_agent_or_404(db, agent_id)
    owner = db.query(User).filter(User.id == agent.user_id, User.is_deleted == False).first()
    if not owner:
        raise HTTPException(status_code=409, detail="Agent 所属用户不可用")
    validate_run_request(db, owner, script_id, params, environment_id)

    rule_type = values.get("schedule_type", schedule.schedule_type)
    interval_seconds = values.get("interval_seconds", schedule.interval_seconds)
    cron_expression = values.get("cron_expression", schedule.cron_expression)
    timezone_name = values.get("timezone", schedule.timezone)
    if rule_type == "interval":
        if interval_seconds is None:
            raise HTTPException(status_code=422, detail="interval 调度必须提供 interval_seconds")
        cron_expression = None
    else:
        interval_seconds = None
        try:
            cron_expression = validate_cron_expression(cron_expression or "")
            timezone_name = validate_timezone(timezone_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    rule_changed = any(key in values for key in (
        "schedule_type", "interval_seconds", "cron_expression", "timezone"
    ))
    was_enabled = schedule.enabled

    for field in (
        "name", "agent_id", "script_id", "environment_id",
        "expires_after_seconds", "enabled", "next_run_at",
    ):
        if field in values:
            value = values[field]
            if field == "name":
                value = value.strip()
            elif field == "next_run_at":
                value = _utc_naive(value)
            setattr(schedule, field, value)
    schedule.schedule_type = rule_type
    schedule.interval_seconds = interval_seconds
    schedule.cron_expression = cron_expression
    schedule.timezone = timezone_name
    if (rule_changed or (values.get("enabled") is True and not was_enabled)
            or (rule_type == "cron" and "next_run_at" in values)):
        schedule.next_run_at = utc_naive(next_schedule_time(
            schedule_type=rule_type, after=datetime.now(timezone.utc),
            interval_seconds=interval_seconds, cron_expression=cron_expression,
            timezone_name=timezone_name,
        ))
    if "params" in values:
        schedule.params = json.dumps(params, ensure_ascii=False)
    schedule.updated_by = current_user.id
    db.commit()
    db.refresh(schedule)
    write_audit(
        current_user.id,
        current_user.username,
        "managed_schedule.update",
        target_type="managed_schedule",
        target_id=schedule.id,
        detail="fields={}".format(",".join(sorted(values))),
    )
    return _schedule_item(schedule)


@router.delete("/managed-schedules/{schedule_id}")
def delete_managed_schedule(
    schedule_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    schedule = _schedule_or_404(db, schedule_id)
    schedule.enabled = False
    schedule.is_deleted = True
    schedule.updated_by = current_user.id
    db.commit()
    write_audit(
        current_user.id,
        current_user.username,
        "managed_schedule.delete",
        target_type="managed_schedule",
        target_id=schedule.id,
    )
    return {"message": "托管计划已删除"}


@router.post("/managed-schedules/{schedule_id}/enable", response_model=ManagedScheduleItem)
def enable_managed_schedule(
    schedule_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    schedule = _schedule_or_404(db, schedule_id)
    schedule.enabled = True
    schedule.next_run_at = utc_naive(next_schedule_time(
        schedule_type=schedule.schedule_type, after=datetime.now(timezone.utc),
        interval_seconds=schedule.interval_seconds, cron_expression=schedule.cron_expression,
        timezone_name=schedule.timezone,
    ))
    schedule.updated_by = current_user.id
    db.commit()
    db.refresh(schedule)
    write_audit(current_user.id, current_user.username, "managed_schedule.enable", "managed_schedule", schedule.id)
    return _schedule_item(schedule)


@router.post("/managed-schedules/{schedule_id}/disable", response_model=ManagedScheduleItem)
def disable_managed_schedule(
    schedule_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    schedule = _schedule_or_404(db, schedule_id)
    schedule.enabled = False
    schedule.updated_by = current_user.id
    db.commit()
    db.refresh(schedule)
    write_audit(current_user.id, current_user.username, "managed_schedule.disable", "managed_schedule", schedule.id)
    return _schedule_item(schedule)


@router.post("/managed-schedules/{schedule_id}/run-now", response_model=RunBrief)
def run_managed_schedule_now(
    schedule_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    schedule = _schedule_or_404(db, schedule_id)
    now = datetime.now(timezone.utc)
    run = _create_schedule_run(db, schedule, current_user.id, now=now, scheduled_for=now)
    schedule.last_run_at = now
    schedule.updated_by = current_user.id
    db.commit()
    db.refresh(run)
    write_audit(
        current_user.id,
        current_user.username,
        "managed_schedule.run_now",
        target_type="run",
        target_id=run.id,
        detail="schedule={}".format(schedule.id),
    )
    return _enrich_run(run, db)
