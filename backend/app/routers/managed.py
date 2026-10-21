"""Admin-only managed Agent dispatch and fixed-interval schedule APIs."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import Agent, Environment, ManagedSchedule, Run, Script, User
from app.routers.agents import AgentItem
from app.routers.runs import _enrich_run, _has_result_files
from app.schemas import RunBrief
from app.services.agent_thumbnails import thumbnail_path
from app.services.audit import write_audit
from app.services.run_dispatch import create_validated_run, validate_run_request
from app.services.script_access import restrict_script_query
from app.services.schedule_time import (
    next_schedule_time, utc_naive, validate_cron_expression, validate_timezone,
)

router = APIRouter(prefix="/api/admin", tags=["managed-agents"])


class ManagedRunSummary(BaseModel):
    id: int
    status: str
    dispatch_type: str
    script_id: int
    script_name: Optional[str] = None
    schedule_id: Optional[int] = None
    scheduled_for: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_summary: Optional[str] = None
    has_result_files: bool = False


class ManagedAgentItem(AgentItem):
    thumbnail_updated_at: Optional[datetime] = None
    thumbnail_size: Optional[int] = None
    pending_count: int = 0
    earliest_pending: Optional[ManagedRunSummary] = None
    current_run: Optional[ManagedRunSummary] = None
    latest_run: Optional[ManagedRunSummary] = None
    # Retained for older admin clients.
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
    latest_run_id: Optional[int] = None
    latest_run_status: Optional[str] = None


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


def _error_summary(value: Optional[str], limit: int = 240) -> Optional[str]:
    if not value:
        return None
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else "{}…".format(compact[:limit - 1])


def _managed_run_summaries(db: Session, runs: List[Run]) -> Dict[int, ManagedRunSummary]:
    if not runs:
        return {}
    script_ids = {run.script_id for run in runs}
    scripts = {
        item.id: item.name
        for item in db.query(Script.id, Script.name).filter(Script.id.in_(script_ids)).all()
    }
    return {
        run.id: ManagedRunSummary(
            id=run.id,
            status=run.status,
            dispatch_type=run.dispatch_type,
            script_id=run.script_id,
            script_name=scripts.get(run.script_id),
            schedule_id=run.schedule_id,
            scheduled_for=run.scheduled_for,
            expires_at=run.expires_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error_summary=_error_summary(run.error_msg),
            has_result_files=_has_result_files(run.result_files),
        )
        for run in runs
    }


def _latest_runs_by_schedule(
    db: Session, schedule_ids: List[int]
) -> Dict[int, Run]:
    if not schedule_ids:
        return {}
    latest_ids = db.query(
        Run.schedule_id.label("schedule_id"),
        func.max(Run.id).label("run_id"),
    ).filter(
        Run.schedule_id.in_(schedule_ids),
        Run.is_deleted == False,
    ).group_by(Run.schedule_id).subquery()
    runs = db.query(Run).join(
        latest_ids, Run.id == latest_ids.c.run_id
    ).all()
    return {run.schedule_id: run for run in runs}


def _schedule_item(
    schedule: ManagedSchedule, latest_run: Optional[Run] = None
) -> ManagedScheduleItem:
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
        latest_run_id=latest_run.id if latest_run else None,
        latest_run_status=latest_run.status if latest_run else None,
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
    pending_count = {agent_id: 0 for agent_id in agent_ids}
    pending_by_agent: Dict[int, Run] = {}
    running_by_agent: Dict[int, Run] = {}
    latest_by_agent: Dict[int, Run] = {}
    selected_runs: List[Run] = []
    if agent_ids:
        now = datetime.now(timezone.utc)
        pending_runs = db.query(Run).filter(
            Run.target_agent_id.in_(agent_ids),
            Run.status == "pending",
            Run.is_deleted == False,
            or_(Run.expires_at.is_(None), Run.expires_at > now),
        ).order_by(
            Run.target_agent_id.asc(), Run.scheduled_for.asc(), Run.created_at.asc(), Run.id.asc()
        ).all()
        for run in pending_runs:
            pending_count[run.target_agent_id] += 1
            pending_by_agent.setdefault(run.target_agent_id, run)

        running_runs = db.query(Run).filter(
            Run.status == "running",
            Run.is_deleted == False,
            or_(Run.target_agent_id.in_(agent_ids), Run.agent_id.in_(agent_ids)),
        ).order_by(Run.started_at.asc(), Run.id.asc()).all()
        for run in running_runs:
            device_id = run.target_agent_id or run.agent_id
            if device_id in pending_count:
                running_by_agent.setdefault(device_id, run)

        device_id_expr = func.coalesce(Run.target_agent_id, Run.agent_id)
        ranked_terminal = db.query(
            Run.id.label("run_id"),
            device_id_expr.label("device_id"),
            func.row_number().over(
                partition_by=device_id_expr,
                order_by=(Run.finished_at.desc(), Run.id.desc()),
            ).label("position"),
        ).filter(
            device_id_expr.in_(agent_ids),
            Run.status.in_(["success", "failed", "cancelled", "expired"]),
            Run.dispatch_type.in_(["managed_manual", "managed_schedule"]),
            Run.is_deleted == False,
        ).subquery()
        terminal_rows = db.query(Run, ranked_terminal.c.device_id).join(
            ranked_terminal, Run.id == ranked_terminal.c.run_id
        ).filter(ranked_terminal.c.position == 1).all()
        for run, device_id in terminal_rows:
            latest_by_agent[device_id] = run

        selected_runs = list({
            run.id: run for run in (
                list(pending_by_agent.values())
                + list(running_by_agent.values())
                + list(latest_by_agent.values())
            )
        }.values())
    summaries = _managed_run_summaries(db, selected_runs)
    return [
        ManagedAgentItem.model_validate(agent).model_copy(
            update={
                "pending_count": pending_count.get(agent.id, 0),
                "earliest_pending": summaries.get(pending_by_agent.get(agent.id).id)
                if pending_by_agent.get(agent.id) else None,
                "current_run": summaries.get(running_by_agent.get(agent.id).id)
                if running_by_agent.get(agent.id) else None,
                "latest_run": summaries.get(latest_by_agent.get(agent.id).id)
                if latest_by_agent.get(agent.id) else None,
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


@router.post("/managed-runs/{run_id}/retry", response_model=RunBrief)
def retry_managed_run(
    run_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    original = db.query(Run).filter(
        Run.id == run_id,
        Run.dispatch_type.in_(["managed_manual", "managed_schedule"]),
        Run.is_deleted == False,
    ).first()
    if not original:
        raise HTTPException(status_code=404, detail="托管运行记录不存在")
    if original.status not in ("failed", "expired", "cancelled"):
        raise HTTPException(status_code=409, detail="仅失败、过期或已取消的托管任务可重试")
    if original.target_agent_id is None:
        raise HTTPException(status_code=409, detail="原任务没有目标设备，无法重试")

    agent = _managed_agent_or_404(db, original.target_agent_id, require_enabled=True)
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
            detail="设备正在执行任务 #{}，暂时不能重试".format(running.id),
        )
    try:
        params = json.loads(original.params or "{}")
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=409, detail="原任务参数已损坏，无法重试")
    if not isinstance(params, dict):
        raise HTTPException(status_code=409, detail="原任务参数格式无效，无法重试")

    lifetime_seconds = 3600
    if original.scheduled_for is not None and original.expires_at is not None:
        lifetime_seconds = int((original.expires_at - original.scheduled_for).total_seconds())
    lifetime_seconds = max(60, min(604800, lifetime_seconds))
    now = datetime.now(timezone.utc)
    retry = create_validated_run(
        db,
        run_user=owner,
        script_id=original.script_id,
        params=params,
        environment_id=original.environment_id,
        requested_by=current_user.id,
        dispatch_type=original.dispatch_type,
        target_agent_id=agent.id,
        schedule_id=original.schedule_id,
        scheduled_for=now,
        expires_at=now + timedelta(seconds=lifetime_seconds),
        commit=False,
    )
    retry.retry_of_run_id = original.id
    db.commit()
    db.refresh(retry)
    write_audit(
        current_user.id,
        current_user.username,
        "managed_run.retry",
        target_type="run",
        target_id=retry.id,
        detail="retry_of={} agent={}".format(original.id, agent.id),
    )
    return _enrich_run(retry, db)


@router.get("/managed-schedules", response_model=List[ManagedScheduleItem])
def list_managed_schedules(
    agent_id: Optional[int] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    query = db.query(ManagedSchedule).filter(ManagedSchedule.is_deleted == False)
    if agent_id is not None:
        query = query.filter(ManagedSchedule.agent_id == agent_id)
    if enabled is not None:
        query = query.filter(ManagedSchedule.enabled == enabled)
    schedules = query.order_by(ManagedSchedule.created_at.desc()).all()
    latest_runs = _latest_runs_by_schedule(db, [item.id for item in schedules])
    return [_schedule_item(item, latest_runs.get(item.id)) for item in schedules]


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
    schedule = _schedule_or_404(db, schedule_id)
    latest_run = _latest_runs_by_schedule(db, [schedule.id]).get(schedule.id)
    return _schedule_item(schedule, latest_run)


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
    now = datetime.now(timezone.utc)
    db.query(Run).filter(
        Run.schedule_id == schedule.id,
        Run.status == "pending",
        Run.is_deleted == False,
    ).update(
        {
            Run.status: "cancelled",
            Run.finished_at: now,
            Run.error_msg: "托管计划已删除，待执行任务已取消",
        },
        synchronize_session=False,
    )
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
