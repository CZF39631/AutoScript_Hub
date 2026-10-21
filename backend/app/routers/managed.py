"""Admin-only managed Agent dispatch and fixed-interval schedule APIs."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import require_role
from app.database import get_db
from app.models import (
    Agent, AuditLog, Environment, ManagedAgentBatch, ManagedAgentBatchItem,
    ManagedAgentGroup, ManagedSchedule, Run, Script, User,
)
from app.routers.agents import AgentItem
from app.routers.runs import _enrich_run, _has_result_files
from app.schemas import RunBrief
from app.services.agent_thumbnails import thumbnail_path
from app.services.audit import write_audit
from app.services.managed_agent_lifecycle import (
    delete_agent as delete_agent_lifecycle,
    disable_agent,
    enable_agent,
    preview_agent_impact,
)
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


class ManagedAgentGroupBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


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
    groups: List[ManagedAgentGroupBrief] = Field(default_factory=list)


class ManagedAgentPage(BaseModel):
    items: List[ManagedAgentItem]
    total: int
    page: int
    page_size: int
    pages: int


class ManagedRunCreate(BaseModel):
    script_id: int
    params: Dict[str, Any] = Field(default_factory=dict)
    environment_id: Optional[int] = None
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)


class ManagedAgentUpdate(BaseModel):
    enabled: bool
    impact_version: Optional[str] = None


class ManagedAgentGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)


class ManagedAgentGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)


class ManagedAgentGroupItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class ManagedAgentGroupMembersUpdate(BaseModel):
    agent_ids: List[int] = Field(default_factory=list, max_length=200)


class ManagedAgentGroupsUpdate(BaseModel):
    group_ids: List[int] = Field(default_factory=list, max_length=50)


class ManagedAgentFilters(BaseModel):
    query: Optional[str] = Field(default=None, max_length=200)
    status: Optional[Literal["online", "offline", "disabled"]] = None
    run_status: Optional[Literal["idle", "pending", "running", "success", "failed", "cancelled", "expired"]] = None
    group_id: Optional[int] = None
    sort: str = "-last_heartbeat"


class ManagedBatchSelection(BaseModel):
    mode: Literal["explicit", "all"]
    agent_ids: List[int] = Field(default_factory=list, max_length=200)
    filters: Optional[ManagedAgentFilters] = None

    @model_validator(mode="after")
    def validate_selection(self):
        if self.mode == "explicit" and not self.agent_ids:
            raise ValueError("明确选择至少需要一台设备")
        if self.mode == "all" and self.agent_ids:
            raise ValueError("全部筛选结果模式不可同时传 agent_ids")
        return self


BatchOperation = Literal["dispatch_run", "pause_agents", "resume_agents", "pause_schedules", "set_groups"]


class ManagedBatchRequest(BaseModel):
    operation: BatchOperation
    selection: ManagedBatchSelection
    script_id: Optional[int] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    environment_id: Optional[int] = None
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)
    group_ids: Optional[List[int]] = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_operation_payload(self):
        if self.operation == "dispatch_run" and self.script_id is None:
            raise ValueError("批量发布临时任务必须选择脚本")
        if self.operation == "set_groups" and self.group_ids is None:
            raise ValueError("调整设备组必须提供 group_ids")
        return self


class ManagedBatchItemResult(BaseModel):
    agent_id: int
    machine_name: str
    result: Literal["success", "failed", "skipped"]
    reason: Optional[str] = None
    run_id: Optional[int] = None
    impact: Optional[Dict[str, Any]] = None


class ManagedBatchResult(BaseModel):
    batch_id: Optional[int] = None
    operation: BatchOperation
    total: int
    success: int
    failed: int
    skipped: int
    items: List[ManagedBatchItemResult]
    replayed: bool = False


class ImpactHistoryPolicy(BaseModel):
    runs_retained: bool
    schedules_retained: bool
    message: str


class ImpactIdentityRecovery(BaseModel):
    can_restore: bool
    automatic_restore: bool
    method: str
    message: str


class ManagedAgentImpact(BaseModel):
    action: Literal["disable", "delete"]
    agent_id: int
    machine_name: str
    version: str
    pending_count: int
    running_count: int
    enabled_schedule_count: int
    paused_schedule_count: int
    thumbnail_exists: bool
    history_policy: ImpactHistoryPolicy
    identity_recovery: ImpactIdentityRecovery


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
    last_missed_at: Optional[datetime] = None
    last_missed_reason: Optional[str] = None
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
        last_missed_at=schedule.last_missed_at,
        last_missed_reason=schedule.last_missed_reason,
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


def _apply_managed_agent_filters(
    query, *, search: Optional[str] = None, status: Optional[str] = None,
    run_status: Optional[str] = None, group_id: Optional[int] = None,
):
    if search and search.strip():
        term = "%{}%".format(search.strip().lower())
        query = query.filter(or_(
            func.lower(Agent.machine_name).like(term),
            func.lower(func.coalesce(Agent.machine_ip, "")).like(term),
            func.lower(func.coalesce(Agent.agent_version, "")).like(term),
            func.lower(Agent.device_uid).like(term),
        ))
    if status == "disabled":
        query = query.filter(Agent.enabled == False)
    elif status in ("online", "offline"):
        query = query.filter(Agent.enabled == True, Agent.status == status)
    if group_id is not None:
        query = query.filter(Agent.managed_groups.any(ManagedAgentGroup.id == group_id))
    if run_status:
        active = exists().where(and_(
            or_(Run.target_agent_id == Agent.id, Run.agent_id == Agent.id),
            Run.status.in_(["pending", "running"]), Run.is_deleted == False,
        ))
        if run_status == "idle":
            query = query.filter(~active)
        else:
            query = query.filter(exists().where(and_(
                or_(Run.target_agent_id == Agent.id, Run.agent_id == Agent.id),
                Run.status == run_status, Run.is_deleted == False,
            )))
    return query


def _managed_agent_order(sort: str):
    descending = sort.startswith("-")
    key = sort[1:] if descending else sort
    columns = {
        "name": Agent.machine_name,
        "status": Agent.status,
        "last_heartbeat": Agent.last_heartbeat,
        "created_at": Agent.created_at,
    }
    column = columns.get(key)
    if column is None:
        raise HTTPException(status_code=422, detail="不支持的设备排序字段")
    return [column.desc() if descending else column.asc(), Agent.id.asc()]


def _serialize_managed_agents(db: Session, agents: List[Agent]) -> List[ManagedAgentItem]:
    agent_ids = [agent.id for agent in agents]
    pending_count = {agent_id: 0 for agent_id in agent_ids}
    pending_by_agent: Dict[int, Run] = {}
    running_by_agent: Dict[int, Run] = {}
    latest_by_agent: Dict[int, Run] = {}
    selected_runs: List[Run] = []
    if agent_ids:
        now = datetime.now(timezone.utc)
        pending_runs = db.query(Run).filter(
            Run.target_agent_id.in_(agent_ids), Run.status == "pending",
            Run.is_deleted == False, or_(Run.expires_at.is_(None), Run.expires_at > now),
        ).order_by(
            Run.target_agent_id.asc(), Run.scheduled_for.asc(), Run.created_at.asc(), Run.id.asc()
        ).all()
        for run in pending_runs:
            pending_count[run.target_agent_id] += 1
            pending_by_agent.setdefault(run.target_agent_id, run)

        running_runs = db.query(Run).filter(
            Run.status == "running", Run.is_deleted == False,
            or_(Run.target_agent_id.in_(agent_ids), Run.agent_id.in_(agent_ids)),
        ).order_by(Run.started_at.asc(), Run.id.asc()).all()
        for run in running_runs:
            device_id = run.target_agent_id or run.agent_id
            if device_id in pending_count:
                running_by_agent.setdefault(device_id, run)

        device_id_expr = func.coalesce(Run.target_agent_id, Run.agent_id)
        ranked_terminal = db.query(
            Run.id.label("run_id"), device_id_expr.label("device_id"),
            func.row_number().over(
                partition_by=device_id_expr, order_by=(Run.finished_at.desc(), Run.id.desc()),
            ).label("position"),
        ).filter(
            device_id_expr.in_(agent_ids),
            Run.status.in_(["success", "failed", "cancelled", "expired"]),
            Run.dispatch_type.in_(["managed_manual", "managed_schedule"]),
            Run.is_deleted == False,
        ).subquery()
        for run, device_id in db.query(Run, ranked_terminal.c.device_id).join(
            ranked_terminal, Run.id == ranked_terminal.c.run_id
        ).filter(ranked_terminal.c.position == 1).all():
            latest_by_agent[device_id] = run
        selected_runs = list({run.id: run for run in (
            list(pending_by_agent.values()) + list(running_by_agent.values())
            + list(latest_by_agent.values())
        )}.values())
    summaries = _managed_run_summaries(db, selected_runs)
    return [ManagedAgentItem.model_validate(agent).model_copy(update={
        "pending_count": pending_count.get(agent.id, 0),
        "earliest_pending": summaries.get(pending_by_agent[agent.id].id) if agent.id in pending_by_agent else None,
        "current_run": summaries.get(running_by_agent[agent.id].id) if agent.id in running_by_agent else None,
        "latest_run": summaries.get(latest_by_agent[agent.id].id) if agent.id in latest_by_agent else None,
        "running_run_id": running_by_agent[agent.id].id if agent.id in running_by_agent else None,
        "running_dispatch_type": running_by_agent[agent.id].dispatch_type if agent.id in running_by_agent else None,
        "groups": [ManagedAgentGroupBrief.model_validate(group) for group in agent.managed_groups if not group.is_deleted],
    }) for agent in agents]


@router.get("/managed-agents", response_model=List[ManagedAgentItem])
def list_managed_agents(
    enabled: Optional[bool] = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Legacy unpaged response retained for existing admin clients."""
    query = db.query(Agent).options(selectinload(Agent.managed_groups)).filter(
        Agent.mode == "managed", Agent.is_deleted == False,
    )
    if enabled is not None:
        query = query.filter(Agent.enabled == enabled)
    agents = query.order_by(Agent.enabled.desc(), Agent.last_heartbeat.desc(), Agent.id.asc()).all()
    return _serialize_managed_agents(db, agents)


@router.get("/managed-agents/paged", response_model=ManagedAgentPage)
def list_managed_agents_paged(
    query: Optional[str] = Query(default=None, max_length=200),
    status: Optional[Literal["online", "offline", "disabled"]] = Query(default=None),
    run_status: Optional[Literal["idle", "pending", "running", "success", "failed", "cancelled", "expired"]] = Query(default=None),
    group_id: Optional[int] = Query(default=None, ge=1),
    sort: str = Query(default="-last_heartbeat"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    base = db.query(Agent).filter(Agent.mode == "managed", Agent.is_deleted == False)
    base = _apply_managed_agent_filters(
        base, search=query, status=status, run_status=run_status, group_id=group_id,
    )
    total = base.count()
    agents = base.options(selectinload(Agent.managed_groups)).order_by(
        *_managed_agent_order(sort)
    ).offset((page - 1) * page_size).limit(page_size).all()
    return ManagedAgentPage(
        items=_serialize_managed_agents(db, agents), total=total, page=page,
        page_size=page_size, pages=max(1, (total + page_size - 1) // page_size),
    )


def _group_item(db: Session, group: ManagedAgentGroup) -> ManagedAgentGroupItem:
    count = db.query(func.count()).select_from(Agent).filter(
        Agent.mode == "managed", Agent.is_deleted == False,
        Agent.managed_groups.any(ManagedAgentGroup.id == group.id),
    ).scalar() or 0
    return ManagedAgentGroupItem(
        id=group.id, name=group.name, description=group.description,
        member_count=count, created_at=group.created_at, updated_at=group.updated_at,
    )


def _managed_group_or_404(db: Session, group_id: int) -> ManagedAgentGroup:
    group = db.query(ManagedAgentGroup).filter(
        ManagedAgentGroup.id == group_id, ManagedAgentGroup.is_deleted == False,
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="设备分组不存在")
    return group


@router.get("/managed-agent-groups", response_model=List[ManagedAgentGroupItem])
def list_managed_agent_groups(
    current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    groups = db.query(ManagedAgentGroup).filter(
        ManagedAgentGroup.is_deleted == False
    ).order_by(ManagedAgentGroup.name.asc(), ManagedAgentGroup.id.asc()).all()
    return [_group_item(db, group) for group in groups]


@router.post("/managed-agent-groups", response_model=ManagedAgentGroupItem)
def create_managed_agent_group(
    req: ManagedAgentGroupCreate,
    current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="分组名称不能为空")
    if db.query(ManagedAgentGroup).filter(
        func.lower(ManagedAgentGroup.name) == name.lower(), ManagedAgentGroup.is_deleted == False,
    ).first():
        raise HTTPException(status_code=409, detail="设备分组名称已存在")
    group = ManagedAgentGroup(
        name=name, description=req.description, created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    write_audit(current_user.id, current_user.username, "managed_agent_group.create",
                "managed_agent_group", group.id, detail="name={}".format(name), db=db)
    return _group_item(db, group)


@router.patch("/managed-agent-groups/{group_id}", response_model=ManagedAgentGroupItem)
def update_managed_agent_group(
    group_id: int, req: ManagedAgentGroupUpdate,
    current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    group = _managed_group_or_404(db, group_id)
    values = req.model_dump(exclude_unset=True)
    if "name" in values:
        name = values["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="分组名称不能为空")
        duplicate = db.query(ManagedAgentGroup).filter(
            func.lower(ManagedAgentGroup.name) == name.lower(),
            ManagedAgentGroup.id != group.id, ManagedAgentGroup.is_deleted == False,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="设备分组名称已存在")
        group.name = name
    if "description" in values:
        group.description = values["description"]
    group.updated_by = current_user.id
    db.commit()
    db.refresh(group)
    write_audit(current_user.id, current_user.username, "managed_agent_group.update",
                "managed_agent_group", group.id, detail="fields={}".format(",".join(sorted(values))), db=db)
    return _group_item(db, group)


@router.delete("/managed-agent-groups/{group_id}")
def delete_managed_agent_group(
    group_id: int, current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    group = _managed_group_or_404(db, group_id)
    member_count = len(group.agents)
    group.agents = []
    # Keep the audit row while releasing the unique human-facing name for reuse.
    group.name = "{} [deleted:{}]".format(group.name[:75], group.id)
    group.is_deleted = True
    group.updated_by = current_user.id
    db.commit()
    write_audit(current_user.id, current_user.username, "managed_agent_group.delete",
                "managed_agent_group", group.id, detail="members_removed={}".format(member_count), db=db)
    return {"message": "设备分组已删除", "members_removed": member_count}


@router.put("/managed-agent-groups/{group_id}/members", response_model=ManagedAgentGroupItem)
def replace_managed_agent_group_members(
    group_id: int, req: ManagedAgentGroupMembersUpdate,
    current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    group = _managed_group_or_404(db, group_id)
    ids = list(dict.fromkeys(req.agent_ids))
    agents = db.query(Agent).filter(
        Agent.id.in_(ids), Agent.mode == "managed", Agent.is_deleted == False,
    ).all() if ids else []
    if len(agents) != len(ids):
        raise HTTPException(status_code=422, detail="成员列表包含不存在的托管设备")
    group.agents = agents
    group.updated_by = current_user.id
    db.commit()
    db.refresh(group)
    write_audit(current_user.id, current_user.username, "managed_agent_group.members.replace",
                "managed_agent_group", group.id, detail="member_count={}".format(len(agents)), db=db)
    return _group_item(db, group)


@router.put("/managed-agents/{agent_id}/groups", response_model=List[ManagedAgentGroupBrief])
def replace_managed_agent_groups(
    agent_id: int, req: ManagedAgentGroupsUpdate,
    current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    agent = _managed_agent_or_404(db, agent_id)
    ids = list(dict.fromkeys(req.group_ids))
    groups = db.query(ManagedAgentGroup).filter(
        ManagedAgentGroup.id.in_(ids), ManagedAgentGroup.is_deleted == False,
    ).all() if ids else []
    if len(groups) != len(ids):
        raise HTTPException(status_code=422, detail="分组列表包含不存在的设备分组")
    agent.managed_groups = groups
    db.commit()
    write_audit(current_user.id, current_user.username, "managed_agent.groups.replace",
                "agent", agent.id, detail="group_ids={}".format(",".join(map(str, sorted(ids)))), db=db)
    return [ManagedAgentGroupBrief.model_validate(group) for group in sorted(groups, key=lambda item: (item.name, item.id))]


def _batch_targets(db: Session, selection: ManagedBatchSelection, limit: int) -> tuple[List[Agent], List[int]]:
    query = db.query(Agent).options(selectinload(Agent.managed_groups)).filter(
        Agent.mode == "managed", Agent.is_deleted == False,
    )
    missing: List[int] = []
    if selection.mode == "explicit":
        ids = list(dict.fromkeys(selection.agent_ids))
        agents = query.filter(Agent.id.in_(ids)).order_by(Agent.id.asc()).all()
        found = {agent.id for agent in agents}
        missing = [agent_id for agent_id in ids if agent_id not in found]
        return agents, missing
    filters = selection.filters or ManagedAgentFilters()
    query = _apply_managed_agent_filters(
        query, search=filters.query, status=filters.status,
        run_status=filters.run_status, group_id=filters.group_id,
    )
    agents = query.order_by(*_managed_agent_order(filters.sort)).limit(limit + 1).all()
    if len(agents) > limit:
        raise HTTPException(status_code=413, detail="筛选结果超过单批上限 {} 台，请缩小范围后重试".format(limit))
    return agents, missing


def _batch_item_check(db: Session, agent: Agent, req: ManagedBatchRequest) -> ManagedBatchItemResult:
    operation = req.operation
    impact = None
    try:
        if operation == "dispatch_run":
            if not agent.enabled:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="failed", reason="设备已暂停接单")
            running = db.query(Run.id).filter(
                Run.status == "running", Run.is_deleted == False,
                or_(Run.target_agent_id == agent.id, Run.agent_id == agent.id),
            ).first()
            if running:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="failed", reason="设备正在执行任务 #{}".format(running.id))
            owner = db.query(User).filter(
                User.id == agent.user_id, User.status == "active", User.is_deleted == False,
            ).first()
            if not owner:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="failed", reason="设备所属用户不可用")
            validate_run_request(db, owner, req.script_id, req.params, req.environment_id)
        elif operation == "pause_agents":
            if not agent.enabled:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="skipped", reason="设备已暂停接单")
            impact = preview_agent_impact(db, agent.id, "disable", managed_only=True)
        elif operation == "resume_agents":
            if agent.enabled:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="skipped", reason="设备已在接单")
        elif operation == "pause_schedules":
            enabled_count = db.query(func.count(ManagedSchedule.id)).filter(
                ManagedSchedule.agent_id == agent.id, ManagedSchedule.enabled == True,
                ManagedSchedule.is_deleted == False,
            ).scalar() or 0
            if not enabled_count:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="skipped", reason="没有启用中的计划")
            impact = {"enabled_schedule_count": enabled_count}
        elif operation == "set_groups":
            impact = {"current_group_ids": sorted(group.id for group in agent.managed_groups if not group.is_deleted),
                      "next_group_ids": sorted(req.group_ids or [])}
            if impact["current_group_ids"] == impact["next_group_ids"]:
                return ManagedBatchItemResult(agent_id=agent.id, machine_name=agent.machine_name, result="skipped", reason="设备分组无需调整", impact=impact)
    except HTTPException as exc:
        return ManagedBatchItemResult(
            agent_id=agent.id, machine_name=agent.machine_name, result="failed",
            reason=str(exc.detail), impact=impact,
        )
    return ManagedBatchItemResult(
        agent_id=agent.id, machine_name=agent.machine_name, result="success",
        reason="验证通过", impact=impact,
    )


def _batch_preview(db: Session, req: ManagedBatchRequest) -> ManagedBatchResult:
    limit = 50 if req.operation == "dispatch_run" else 200
    agents, missing = _batch_targets(db, req.selection, limit)
    if req.operation == "set_groups":
        group_ids = list(dict.fromkeys(req.group_ids or []))
        found = db.query(func.count(ManagedAgentGroup.id)).filter(
            ManagedAgentGroup.id.in_(group_ids), ManagedAgentGroup.is_deleted == False,
        ).scalar() if group_ids else 0
        if found != len(group_ids):
            raise HTTPException(status_code=422, detail="分组列表包含不存在的设备分组")
    items = [_batch_item_check(db, agent, req) for agent in agents]
    items.extend(ManagedBatchItemResult(
        agent_id=agent_id, machine_name="设备 #{}".format(agent_id), result="failed", reason="托管设备不存在",
    ) for agent_id in missing)
    counts = {status: sum(item.result == status for item in items) for status in ("success", "failed", "skipped")}
    return ManagedBatchResult(
        operation=req.operation, total=len(items), success=counts["success"],
        failed=counts["failed"], skipped=counts["skipped"], items=items,
    )


@router.post("/managed-agent-batches/preview", response_model=ManagedBatchResult)
def preview_managed_agent_batch(
    req: ManagedBatchRequest, current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return _batch_preview(db, req)


def _batch_result_from_record(batch: ManagedAgentBatch, *, replayed: bool) -> ManagedBatchResult:
    payload = json.loads(batch.result_json or "{}")
    payload["batch_id"] = batch.id
    payload["replayed"] = replayed
    return ManagedBatchResult.model_validate(payload)


@router.post("/managed-agent-batches", response_model=ManagedBatchResult)
def execute_managed_agent_batch(
    req: ManagedBatchRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    canonical = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = db.query(ManagedAgentBatch).filter(
        ManagedAgentBatch.created_by == current_user.id,
        ManagedAgentBatch.idempotency_key == idempotency_key,
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同的批量请求")
        if not existing.result_json:
            raise HTTPException(status_code=409, detail="相同批量请求仍在处理中")
        return _batch_result_from_record(existing, replayed=True)

    active_since = datetime.now(timezone.utc) - timedelta(minutes=10)
    active_count = db.query(func.count(ManagedAgentBatch.id)).filter(
        ManagedAgentBatch.status == "processing",
        ManagedAgentBatch.created_at >= active_since,
    ).scalar() or 0
    if active_count >= 2:
        raise HTTPException(status_code=429, detail="当前已有 2 个批次在处理，请稍后重试")

    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    burst_count = db.query(func.count(ManagedAgentBatch.id)).filter(
        ManagedAgentBatch.created_by == current_user.id,
        ManagedAgentBatch.created_at >= recent,
    ).scalar() or 0
    if burst_count >= 10:
        raise HTTPException(status_code=429, detail="一分钟内最多执行 10 个批次，请稍后重试")

    preview = _batch_preview(db, req)
    batch = ManagedAgentBatch(
        idempotency_key=idempotency_key, request_hash=request_hash, operation=req.operation,
        status="processing", selection_json=json.dumps(req.selection.model_dump(mode="json"), ensure_ascii=False),
        request_json=canonical, total_count=preview.total, created_by=current_user.id,
    )
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(ManagedAgentBatch).filter(
            ManagedAgentBatch.created_by == current_user.id,
            ManagedAgentBatch.idempotency_key == idempotency_key,
        ).first()
        if concurrent and concurrent.request_hash == request_hash and concurrent.result_json:
            return _batch_result_from_record(concurrent, replayed=True)
        raise HTTPException(status_code=409, detail="相同批量请求已在处理中")
    db.refresh(batch)

    groups = []
    if req.operation == "set_groups" and req.group_ids:
        groups = db.query(ManagedAgentGroup).filter(
            ManagedAgentGroup.id.in_(req.group_ids), ManagedAgentGroup.is_deleted == False,
        ).all()
    executed: List[ManagedBatchItemResult] = []
    agents, _missing = _batch_targets(db, req.selection, 50 if req.operation == "dispatch_run" else 200)
    agents_by_id = {agent.id: agent for agent in agents}
    for item in preview.items:
        if item.result != "success":
            executed.append(item)
            continue
        agent = agents_by_id.get(item.agent_id)
        if not agent:
            executed.append(item.model_copy(update={"result": "failed", "reason": "设备状态已变化"}))
            continue
        current = _batch_item_check(db, agent, req)
        if current.result != "success":
            executed.append(current)
            continue
        try:
            run_id = None
            if req.operation == "dispatch_run":
                owner = db.query(User).filter(User.id == agent.user_id).one()
                now = datetime.now(timezone.utc)
                run = create_validated_run(
                    db, run_user=owner, script_id=req.script_id, params=req.params,
                    environment_id=req.environment_id, requested_by=current_user.id,
                    dispatch_type="managed_manual", target_agent_id=agent.id,
                    scheduled_for=now, expires_at=now + timedelta(seconds=req.expires_in_seconds),
                )
                run_id = run.id
                write_audit(current_user.id, current_user.username, "managed_run.batch_dispatch",
                            "run", run.id, detail="batch={} agent={}".format(batch.id, agent.id), db=db)
            elif req.operation == "pause_agents":
                impact = current.impact or preview_agent_impact(db, agent.id, "disable", managed_only=True)
                disable_agent(db, agent.id, current_user, expected_version=impact["version"], managed_only=True)
            elif req.operation == "resume_agents":
                enable_agent(db, agent.id, current_user, managed_only=True)
            elif req.operation == "pause_schedules":
                changed = db.query(ManagedSchedule).filter(
                    ManagedSchedule.agent_id == agent.id, ManagedSchedule.enabled == True,
                    ManagedSchedule.is_deleted == False,
                ).update({
                    ManagedSchedule.enabled: False, ManagedSchedule.updated_by: current_user.id,
                    ManagedSchedule.updated_at: datetime.now(timezone.utc),
                }, synchronize_session=False)
                db.commit()
                write_audit(current_user.id, current_user.username, "managed_schedule.batch_pause",
                            "agent", agent.id, detail="batch={} schedules={}".format(batch.id, changed), db=db)
            elif req.operation == "set_groups":
                agent.managed_groups = groups
                db.commit()
                write_audit(current_user.id, current_user.username, "managed_agent.groups.batch_replace",
                            "agent", agent.id, detail="batch={} group_ids={}".format(batch.id, req.group_ids or []), db=db)
            executed.append(current.model_copy(update={"reason": "操作成功", "run_id": run_id}))
        except Exception as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc, HTTPException) else "执行失败：{}".format(type(exc).__name__)
            executed.append(current.model_copy(update={"result": "failed", "reason": str(detail)}))

    counts = {status: sum(item.result == status for item in executed) for status in ("success", "failed", "skipped")}
    result = ManagedBatchResult(
        batch_id=batch.id, operation=req.operation, total=len(executed),
        success=counts["success"], failed=counts["failed"], skipped=counts["skipped"], items=executed,
    )
    batch = db.query(ManagedAgentBatch).filter(ManagedAgentBatch.id == batch.id).one()
    persisted_agent_ids = set(agents_by_id)
    for item in executed:
        if item.agent_id not in persisted_agent_ids:
            continue
        db.add(ManagedAgentBatchItem(
            batch_id=batch.id, agent_id=item.agent_id, result=item.result,
            reason=item.reason, run_id=item.run_id,
            detail_json=json.dumps(item.impact, ensure_ascii=False) if item.impact else None,
        ))
    batch.status = "completed"
    batch.success_count = counts["success"]
    batch.failed_count = counts["failed"]
    batch.skipped_count = counts["skipped"]
    batch.completed_at = datetime.now(timezone.utc)
    batch.result_json = result.model_dump_json()
    db.add(AuditLog(
        user_id=current_user.id, username=current_user.username,
        action="managed_agent.batch.execute", target_type="managed_agent_batch", target_id=batch.id,
        detail="operation={} total={} success={} failed={} skipped={}".format(
            req.operation, result.total, result.success, result.failed, result.skipped,
        ), created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    return result


@router.get("/managed-agent-batches/{batch_id}", response_model=ManagedBatchResult)
def get_managed_agent_batch(
    batch_id: int, current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    batch = db.query(ManagedAgentBatch).filter(ManagedAgentBatch.id == batch_id).first()
    if not batch or not batch.result_json:
        raise HTTPException(status_code=404, detail="批次不存在或尚未完成")
    return _batch_result_from_record(batch, replayed=False)


@router.get("/managed-agents/{agent_id}/impact", response_model=ManagedAgentImpact)
def get_managed_agent_impact(
    agent_id: int,
    action: Literal["disable", "delete"] = Query(...),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return preview_agent_impact(db, agent_id, action, managed_only=True)


@router.get("/managed-agents/{agent_id}/thumbnail")
def get_managed_agent_thumbnail(
    agent_id: int,
    request: Request,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agent = _managed_agent_or_404(db, agent_id)
    path = thumbnail_path(agent.id)
    if agent.thumbnail_updated_at is None or agent.thumbnail_size is None or not path.is_file():
        raise HTTPException(status_code=404, detail="缩略图不存在")
    write_audit(
        current_user.id,
        current_user.username,
        "managed_thumbnail.view",
        target_type="agent",
        target_id=agent.id,
        detail="device={}".format(agent.machine_name),
        ip_address=request.client.host if request.client else None,
        db=db,
    )
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
    if req.enabled:
        return enable_agent(db, agent_id, current_user, managed_only=True)
    return disable_agent(
        db,
        agent_id,
        current_user,
        expected_version=req.impact_version,
        managed_only=True,
    )


@router.delete("/managed-agents/{agent_id}")
def delete_managed_agent(
    agent_id: int,
    impact_version: str = Query(...),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return delete_agent_lifecycle(
        db,
        agent_id,
        current_user,
        expected_version=impact_version,
        require_preview=True,
        managed_only=True,
    )


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
    agent_ids: Optional[str] = Query(default=None, max_length=2000),
    enabled: Optional[bool] = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    query = db.query(ManagedSchedule).filter(ManagedSchedule.is_deleted == False)
    if agent_id is not None and agent_ids is not None:
        raise HTTPException(status_code=422, detail="agent_id 与 agent_ids 不可同时使用")
    if agent_id is not None:
        query = query.filter(ManagedSchedule.agent_id == agent_id)
    if agent_ids is not None:
        try:
            parsed_agent_ids = list(dict.fromkeys(
                int(value.strip()) for value in agent_ids.split(",") if value.strip()
            ))
        except ValueError:
            raise HTTPException(status_code=422, detail="agent_ids 必须是逗号分隔的设备 ID")
        if not parsed_agent_ids or len(parsed_agent_ids) > 100 or any(value <= 0 for value in parsed_agent_ids):
            raise HTTPException(status_code=422, detail="agent_ids 必须包含 1 到 100 个有效设备 ID")
        query = query.filter(ManagedSchedule.agent_id.in_(parsed_agent_ids))
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
    agent = _managed_agent_or_404(db, req.agent_id, require_enabled=True)
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
    if not agent.enabled and values.get("enabled", schedule.enabled):
        raise HTTPException(status_code=409, detail="设备已停用，只能维护暂停状态的已有计划")
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
    _managed_agent_or_404(db, schedule.agent_id, require_enabled=True)
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
