import json
import os
import time
from typing import List, Literal, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, tuple_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Script, ScriptVersion, Run, Agent, Group
from app.schemas import ExecuteRequest, RunBrief, RunDetail
from app.auth import get_current_user, verify_agent_token
from app.config import LOGS_DIR, PROJECT_ROOT
from app.services.audit import write_audit
from app.services.run_dispatch import create_validated_run
from app.services.script_lifecycle import lock_script_for_lifecycle
from app.services.script_access import (
    accessible_script_ids,
    accessible_user_ids,
    active_group_ids_for_user,
    get_accessible_script_or_404,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _ensure_aware(dt):
    """SQLite strips tzinfo on round-trip; reattach UTC before arithmetic with aware datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _default_log_file(run_id):
    return os.path.join(LOGS_DIR, "{}.log".format(run_id))


def _resolve_log_file(run, run_id):
    """Locate the log file for a run.

    New Agents upload log chunks into the server's LOGS_DIR. Keep the historical
    locations as read-only fallbacks so existing run records remain viewable.
    Returns the first existing path, or None.
    """
    candidates = []
    if run and run.log_path:
        rp = run.log_path
        candidates.append(rp if os.path.isabs(rp) else os.path.join(PROJECT_ROOT, rp))
    candidates.append(_default_log_file(run_id))
    candidates.append(os.path.join(PROJECT_ROOT, "logs", "{}.log".format(run_id)))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _restrict_run_query(query, current_user):
    if current_user.role == "admin":
        return query
    if current_user.role == "operator":
        return query.filter(Run.user_id == current_user.id)
    return query.filter(or_(
        Run.user_id == current_user.id,
        (
            Run.script_id.in_(accessible_script_ids(current_user))
            & Run.user_id.in_(accessible_user_ids(current_user))
        ),
    ))


def _can_view_run(db, current_user, run):
    return _restrict_run_query(
        db.query(Run).filter(Run.id == run.id), current_user,
    ).first() is not None


def _has_result_files(value) -> bool:
    if not value:
        return False
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return bool(str(value).strip())
    if isinstance(parsed, (list, tuple, dict, str)):
        return bool(parsed)
    return parsed is not None


def _enrich_runs(runs, db, detail=False):
    """Batch-enrich Runs without leaking managed-device result paths."""
    if not runs:
        return []
    user_ids = {run.user_id for run in runs}
    script_ids = {run.script_id for run in runs}
    version_keys = {(run.script_id, run.script_version) for run in runs}
    agent_ids = {
        agent_id for run in runs for agent_id in (run.agent_id, run.target_agent_id)
        if agent_id is not None
    }
    users = {
        item.id: item for item in db.query(User).filter(User.id.in_(user_ids)).all()
    }
    scripts = {
        item.id: item for item in db.query(Script).filter(Script.id.in_(script_ids)).all()
    }
    versions = {
        (item.script_id, item.version): item
        for item in db.query(ScriptVersion).filter(
            tuple_(ScriptVersion.script_id, ScriptVersion.version).in_(version_keys)
        ).all()
    }
    agents = {}
    if agent_ids:
        agents = {
            item.id: item for item in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
        }

    result = []
    schema = RunDetail if detail else RunBrief
    for run in runs:
        item = schema.model_validate(run)
        user = users.get(run.user_id)
        script = scripts.get(run.script_id)
        version = versions.get((run.script_id, run.script_version))
        agent = agents.get(run.agent_id)
        target_agent = agents.get(run.target_agent_id)
        item.username = user.display_name if user else None
        item.script_name = script.name if script else None
        item.script_semantic_version = version.semantic_version if version else None
        item.agent_name = agent.machine_name if agent else None
        item.target_agent_name = target_agent.machine_name if target_agent else None
        item.has_result_files = _has_result_files(run.result_files)
        # Managed results live on the controlled device. Admin/browser responses
        # expose only availability, never the device's absolute local path.
        if run.dispatch_type in ("managed_manual", "managed_schedule"):
            item.result_files = None
        result.append(item)
    return result


def _enrich_run(run, db, detail=False):
    """Backward-compatible single-run wrapper around the batched enricher."""
    return _enrich_runs([run], db, detail=detail)[0]


class RunStatusUpdate(BaseModel):
    status: Literal["success", "failed"]
    error_msg: Optional[str] = None
    result_files: Optional[str] = None
    agent_id: Optional[int] = None


class RunClaimRequest(BaseModel):
    agent_id: int


class RunLogChunk(BaseModel):
    offset: int = Field(ge=0)
    content: str
    agent_id: Optional[int] = None


@router.post("/execute", response_model=RunBrief)
def execute_script(
    req: ExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Fail fast before acquiring the lifecycle write lock.
    get_accessible_script_or_404(db, current_user, req.script_id, require_active=True)

    # Check for active runs — auto-cancel stale pending runs (>5 min)
    active = db.query(Run).filter(
        Run.user_id == current_user.id,
        Run.target_agent_id.is_(None),
        Run.status.in_(["pending", "running"]),
        Run.is_deleted == False,
    ).first()
    if active:
        if active.status == "pending":
            stale_secs = (datetime.now(timezone.utc) - _ensure_aware(active.created_at)).total_seconds()
            if stale_secs > 300:  # 5 minutes
                active.status = "cancelled"
                active.finished_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(active)
            else:
                raise HTTPException(status_code=409, detail="当前有任务正在执行,请等待完成")
        else:
            raise HTTPException(status_code=409, detail="当前有任务正在执行,请等待完成")

    # Stale-pending cleanup above may commit. Shared creation rechecks script
    # access/status under the lifecycle lock and validates params/environment.
    run = create_validated_run(
        db,
        run_user=current_user,
        script_id=req.script_id,
        params=req.params,
        environment_id=req.environment_id,
        requested_by=current_user.id,
        dispatch_type="standard",
        lock_func=lock_script_for_lifecycle,
    )
    script = run.script
    write_audit(current_user.id, current_user.username, "execute_script",
                target_type="run", target_id=run.id,
                detail="script={} v{}".format(script.name, script.latest_version))
    return _enrich_run(run, db)


@router.get("", response_model=List[RunBrief])
def list_runs(
    script_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    schedule_id: Optional[int] = None,
    dispatch_type: Optional[Literal["standard", "managed_manual", "managed_schedule"]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    mine_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Run).filter(Run.is_deleted == False)
    q = _restrict_run_query(q, current_user)
    if mine_only:
        q = q.filter(Run.user_id == current_user.id)
        # Legacy standard Agents poll this exact view without sending an agent id.
        # Keep directed managed work out of that queue; managed Agents use /agents/{id}/next.
        if status == "pending":
            q = q.filter(Run.target_agent_id.is_(None))
    if script_id:
        q = q.filter(Run.script_id == script_id)
    if status:
        q = q.filter(Run.status == status)
    if user_id:
        q = q.filter(Run.user_id == user_id)
    if agent_id is not None:
        q = q.filter(or_(Run.target_agent_id == agent_id, Run.agent_id == agent_id))
    if schedule_id is not None:
        q = q.filter(Run.schedule_id == schedule_id)
    if dispatch_type is not None:
        q = q.filter(Run.dispatch_type == dispatch_type)
    if date_from:
        from datetime import datetime as dt
        try:
            q = q.filter(Run.created_at >= dt.fromisoformat(date_from))
        except ValueError:
            pass  # invalid date format, skip filter
    if date_to:
        from datetime import datetime as dt
        try:
            q = q.filter(Run.created_at < dt.fromisoformat(date_to))
        except ValueError:
            pass  # invalid date format, skip filter

    runs = q.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()

    return _enrich_runs(runs, db)


@router.get("/filter-options/users")
def filter_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "operator":
        return [{"id": current_user.id, "name": current_user.display_name}]
    users_query = db.query(User).filter(User.is_deleted == False)
    if current_user.role == "developer":
        group_ids = active_group_ids_for_user(db, current_user)
        if group_ids:
            users_query = users_query.filter(or_(
                User.id == current_user.id,
                User.groups.any(Group.id.in_(group_ids)),
            ))
        else:
            users_query = users_query.filter(User.id == current_user.id)
    users = users_query.all()
    return [{"id": u.id, "name": u.display_name} for u in users]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if not _can_view_run(db, current_user, run):
        raise HTTPException(status_code=404, detail="执行记录不存在或无访问权限")
    return _enrich_run(run, db, detail=True)


@router.post("/{run_id}/claim", response_model=RunBrief)
def claim_run(
    run_id: int,
    claim: RunClaimRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    """Atomically bind a pending run to exactly one Agent before execution."""
    agent = db.query(Agent).filter(
        Agent.id == claim.agent_id,
        Agent.user_id == current_user.id,
        Agent.enabled == True,
        Agent.is_deleted == False,
    ).first()
    if not agent:
        raise HTTPException(status_code=400, detail="Agent 与任务用户不匹配或已禁用")
    verify_agent_token(agent_token, agent)

    now = datetime.now(timezone.utc)
    candidate = db.query(Run).filter(
        Run.id == run_id,
        Run.user_id == current_user.id,
        Run.is_deleted == False,
    ).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if candidate.expires_at is not None and _ensure_aware(candidate.expires_at) <= now:
        expired = db.query(Run).filter(
            Run.id == run_id,
            Run.status == "pending",
            Run.is_deleted == False,
        ).update(
            {Run.status: "expired", Run.finished_at: now},
            synchronize_session=False,
        )
        if expired == 1:
            db.commit()
        else:
            db.rollback()
        raise HTTPException(status_code=409, detail="任务已过期或已被领取")
    if candidate.scheduled_for is not None and _ensure_aware(candidate.scheduled_for) > now:
        raise HTTPException(status_code=409, detail="任务尚未到执行时间")
    if candidate.target_agent_id is not None and candidate.target_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="任务已定向到其他 Agent")
    if agent.mode == "managed" and candidate.target_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="托管 Agent 只能领取定向任务")
    if agent.mode == "standard" and candidate.target_agent_id is not None:
        raise HTTPException(status_code=403, detail="标准 Agent 不能领取托管任务")

    claimed = db.query(Run).filter(
        Run.id == run_id,
        Run.user_id == current_user.id,
        Run.is_deleted == False,
        Run.status == "pending",
        Run.agent_id.is_(None),
        or_(Run.scheduled_for.is_(None), Run.scheduled_for <= now),
        or_(Run.expires_at.is_(None), Run.expires_at > now),
        or_(Run.target_agent_id.is_(None), Run.target_agent_id == agent.id),
    ).update(
        {
            Run.status: "running",
            Run.agent_id: agent.id,
            Run.claimed_at: now,
            Run.started_at: now,
        },
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
        if not run:
            raise HTTPException(status_code=404, detail="执行记录不存在")
        if run.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无权限领取该任务")
        raise HTTPException(status_code=409, detail="任务已被领取或不再待执行")

    db.commit()
    run = db.query(Run).filter(Run.id == run_id).first()
    return _enrich_run(run, db)


@router.patch("/{run_id}/status")
def update_run_status(
    run_id: int,
    update: RunStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅任务所属用户可更新状态")
    if run.agent_id is None or update.agent_id != run.agent_id:
        raise HTTPException(status_code=403, detail="仅领取任务的 Agent 可更新状态")

    agent = db.query(Agent).filter(
        Agent.id == run.agent_id,
        Agent.user_id == run.user_id,
        Agent.is_deleted == False,
    ).first()
    if not agent:
        raise HTTPException(status_code=400, detail="Agent 与任务用户不匹配")
    verify_agent_token(agent_token, agent)

    now = datetime.now(timezone.utc)
    values = {Run.status: update.status, Run.finished_at: now}
    if run.started_at:
        values[Run.duration_sec] = int((now - _ensure_aware(run.started_at)).total_seconds())
    if update.error_msg is not None:
        values[Run.error_msg] = update.error_msg
    if update.result_files is not None:
        values[Run.result_files] = update.result_files

    # The running predicate is the state transition itself. A concurrent cancel
    # or watchdog failure wins cleanly and cannot be overwritten by completion.
    updated = db.query(Run).filter(
        Run.id == run_id,
        Run.user_id == current_user.id,
        Run.agent_id == update.agent_id,
        Run.status == "running",
        Run.is_deleted == False,
    ).update(values, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="任务已结束或尚未开始，不能更新终态")
    db.commit()
    return {"message": "状态已更新"}


@router.post("/{run_id}/cancel")
def cancel_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if run.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权限取消该任务")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="该任务无法取消")
    now = datetime.now(timezone.utc)
    values = {Run.status: "cancelled", Run.finished_at: now}
    if run.started_at:
        values[Run.duration_sec] = int((now - _ensure_aware(run.started_at)).total_seconds())
    cancelled = db.query(Run).filter(
        Run.id == run_id,
        Run.status.in_(["pending", "running"]),
        Run.is_deleted == False,
    ).update(values, synchronize_session=False)
    if cancelled != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="任务状态已变化，无法取消")
    db.commit()
    write_audit(current_user.id, current_user.username, "cancel_run",
                target_type="run", target_id=run_id)
    return {"message": "任务已取消"}


@router.get("/{run_id}/log")
def get_run_log(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if not _can_view_run(db, current_user, run):
        raise HTTPException(status_code=404, detail="执行记录不存在或无访问权限")

    log_file = _resolve_log_file(run, run_id)
    if not log_file:
        return {"log": ""}
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        return {"log": f.read()}


@router.post("/{run_id}/log/chunk")
def append_run_log_chunk(
    run_id: int,
    chunk: RunLogChunk,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    """Append an Agent log delta using an idempotent UTF-8 byte offset."""
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限上报该任务日志")
    if run.agent_id is not None and chunk.agent_id != run.agent_id:
        raise HTTPException(status_code=403, detail="仅领取任务的 Agent 可上报日志")
    bound_agent_id = run.agent_id or run.target_agent_id
    if bound_agent_id is not None:
        agent = db.query(Agent).filter(
            Agent.id == bound_agent_id,
            Agent.user_id == run.user_id,
            Agent.is_deleted == False,
        ).first()
        if not agent:
            raise HTTPException(status_code=400, detail="Agent 与任务用户不匹配")
        if agent.mode == "managed" and chunk.agent_id != agent.id:
            raise HTTPException(status_code=403, detail="仅目标 Agent 可上报日志")
        verify_agent_token(agent_token, agent)

    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.abspath(_default_log_file(run_id))
    payload = chunk.content.encode("utf-8")

    with open(log_file, "a+b") as f:
        f.seek(0, os.SEEK_END)
        current_offset = f.tell()
        if chunk.offset > current_offset:
            raise HTTPException(
                status_code=409,
                detail={"message": "日志偏移不连续", "offset": current_offset},
            )

        if chunk.offset < current_offset:
            f.seek(chunk.offset)
            existing = f.read(min(len(payload), current_offset - chunk.offset))
            if existing != payload[:len(existing)]:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "日志内容与服务器偏移冲突", "offset": current_offset},
                )
            payload = payload[len(existing):]

        if payload:
            f.seek(0, os.SEEK_END)
            f.write(payload)
            f.flush()
        f.seek(0, os.SEEK_END)
        acknowledged_offset = f.tell()

    run.log_path = log_file
    db.commit()
    return {"offset": acknowledged_offset}


@router.get("/{run_id}/log/stream")
def stream_run_log(
    run_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    import jwt
    from jwt import InvalidTokenError
    from app.config import JWT_SECRET, JWT_ALGORITHM
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("kind") == "agent":
            raise InvalidTokenError("agent token cannot authenticate log streaming")
        user_id = int(payload.get("sub"))
    except (InvalidTokenError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="无效的令牌")
    current_user = db.query(User).filter(
        User.id == user_id, User.status == "active", User.is_deleted == False
    ).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户不存在")

    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if not _can_view_run(db, current_user, run):
        raise HTTPException(status_code=404, detail="执行记录不存在或无访问权限")

    log_file = _resolve_log_file(run, run_id)
    if not log_file:
        # Log not generated yet (run just started) — watch the Agent's default location
        # so the SSE generator can stream content as soon as the file appears.
        log_file = _default_log_file(run_id)

    def event_generator():
        from app.database import SessionLocal
        pos = 0
        idle_count = 0
        while True:
            db2 = SessionLocal()
            try:
                r = db2.query(Run).filter(Run.id == run_id).first()
                alive = r and r.status in ("pending", "running")
            finally:
                db2.close()

            if os.path.isfile(log_file):
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                if chunk:
                    idle_count = 0
                    yield "data: {}\n\n".format(json.dumps({"log": chunk}, ensure_ascii=False))
                else:
                    idle_count += 1
            else:
                idle_count += 1

            if not alive:
                yield "data: {\"done\": true}\n\n"
                break
            # Timeout: no new data for 600s while alive
            if idle_count > 600:
                yield "data: {\"done\": true}\n\n"
                break

            time.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
