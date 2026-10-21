"""Preview and apply Agent disable/delete lifecycle effects consistently."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Agent, AuditLog, ManagedSchedule, Run, User
from app.services.agent_thumbnails import delete_thumbnail, thumbnail_path

LifecycleAction = Literal["disable", "delete"]


def _timestamp(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat(timespec="microseconds")


def _agent_or_404(db: Session, agent_id: int, *, managed_only: bool) -> Agent:
    query = db.query(Agent).filter(Agent.id == agent_id, Agent.is_deleted == False)
    if managed_only:
        query = query.filter(Agent.mode == "managed")
    agent = query.with_for_update().first()
    if not agent:
        detail = "托管 Agent 不存在或不可用" if managed_only else "Agent 不存在"
        raise HTTPException(status_code=404, detail=detail)
    return agent


def _snapshot(db: Session, agent: Agent, action: LifecycleAction) -> Dict[str, Any]:
    pending = db.query(Run).filter(
        Run.target_agent_id == agent.id,
        Run.status == "pending",
        Run.is_deleted == False,
    ).order_by(Run.id.asc()).all()
    running = db.query(Run).filter(
        or_(Run.target_agent_id == agent.id, Run.agent_id == agent.id),
        Run.status == "running",
        Run.is_deleted == False,
    ).order_by(Run.id.asc()).all()
    schedules = db.query(ManagedSchedule).filter(
        ManagedSchedule.agent_id == agent.id,
        ManagedSchedule.is_deleted == False,
    ).order_by(ManagedSchedule.id.asc()).all()
    enabled_schedules = [item for item in schedules if item.enabled]
    paused_schedules = [item for item in schedules if not item.enabled]
    thumbnail_exists = thumbnail_path(agent.id).is_file()

    version_source = {
        "action": action,
        "agent": {
            "id": agent.id,
            "enabled": agent.enabled,
            "status": agent.status,
            "updated_at": _timestamp(agent.updated_at),
            "thumbnail_updated_at": _timestamp(agent.thumbnail_updated_at),
            "thumbnail_size": agent.thumbnail_size,
            "thumbnail_exists": thumbnail_exists,
        },
        "pending": [
            [item.id, item.status, _timestamp(item.updated_at)] for item in pending
        ],
        "running": [
            [item.id, item.status, _timestamp(item.updated_at)] for item in running
        ],
        "schedules": [
            [item.id, item.enabled, item.is_deleted, _timestamp(item.updated_at)]
            for item in schedules
        ],
    }
    version = hashlib.sha256(
        json.dumps(version_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    if action == "disable":
        identity_recovery = {
            "can_restore": True,
            "automatic_restore": False,
            "method": "admin_enable",
            "message": "管理员可通过“恢复接单”重新启用；设备自身重新连接不会自动恢复接单。",
        }
    else:
        identity_recovery = {
            "can_restore": False,
            "automatic_restore": False,
            "method": "new_authorization_required",
            "message": "删除后同一 device_uid 会被拒绝自动注册，当前记录不可自动恢复；如需再次接入，必须重新授权新的设备身份。",
        }

    return {
        "action": action,
        "agent_id": agent.id,
        "machine_name": agent.machine_name,
        "version": version,
        "pending_count": len(pending),
        "running_count": len(running),
        "enabled_schedule_count": len(enabled_schedules),
        "paused_schedule_count": len(paused_schedules),
        "thumbnail_exists": thumbnail_exists,
        "history_policy": {
            "runs_retained": True,
            "schedules_retained": True,
            "message": "任务运行历史和计划记录均会保留，关联启用计划将暂停。",
        },
        "identity_recovery": identity_recovery,
    }


def preview_agent_impact(
    db: Session,
    agent_id: int,
    action: LifecycleAction,
    *,
    managed_only: bool = True,
) -> Dict[str, Any]:
    agent = _agent_or_404(db, agent_id, managed_only=managed_only)
    return _snapshot(db, agent, action)


def _assert_current_version(impact: Dict[str, Any], expected_version: Optional[str]) -> None:
    if not expected_version:
        raise HTTPException(status_code=409, detail="请先获取最新影响预览后再确认操作")
    if expected_version != impact["version"]:
        raise HTTPException(status_code=409, detail="设备状态已变化，请刷新影响预览后重新确认")


def _audit(
    db: Session,
    actor: User,
    action: str,
    agent_id: int,
    impact: Dict[str, Any],
) -> None:
    detail = (
        "pending={pending_count} running={running_count} "
        "enabled_schedules={enabled_schedule_count} paused_schedules={paused_schedule_count} "
        "thumbnail={thumbnail_exists} history_retained=true"
    ).format(**impact)
    db.add(AuditLog(
        user_id=actor.id,
        username=actor.username,
        action=action,
        target_type="agent",
        target_id=agent_id,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    ))


def _stop_active_work(db: Session, agent: Agent, reason: str, actor_id: int) -> None:
    now = datetime.now(timezone.utc)
    db.query(Run).filter(
        Run.target_agent_id == agent.id,
        Run.status == "pending",
        Run.is_deleted == False,
    ).update(
        {
            Run.status: "cancelled",
            Run.finished_at: now,
            Run.error_msg: "{}，待执行任务已取消".format(reason),
            Run.updated_at: now,
        },
        synchronize_session=False,
    )
    db.query(Run).filter(
        or_(Run.target_agent_id == agent.id, Run.agent_id == agent.id),
        Run.status == "running",
        Run.is_deleted == False,
    ).update(
        {
            # Managed clients terminate their subprocess only after observing the
            # authoritative cancelled state.  Keep this terminal state stable so
            # a delayed completion report cannot resurrect the run.
            Run.status: "cancelled",
            Run.finished_at: now,
            Run.error_msg: "{}，运行中任务已取消，客户端将终止进程".format(reason),
            Run.updated_at: now,
        },
        synchronize_session=False,
    )
    db.query(ManagedSchedule).filter(
        ManagedSchedule.agent_id == agent.id,
        ManagedSchedule.enabled == True,
        ManagedSchedule.is_deleted == False,
    ).update(
        {
            ManagedSchedule.enabled: False,
            ManagedSchedule.updated_by: actor_id,
            ManagedSchedule.updated_at: now,
        },
        synchronize_session=False,
    )


def disable_agent(
    db: Session,
    agent_id: int,
    actor: User,
    *,
    expected_version: Optional[str],
    managed_only: bool = True,
) -> Agent:
    agent = _agent_or_404(db, agent_id, managed_only=managed_only)
    impact = _snapshot(db, agent, "disable")
    _assert_current_version(impact, expected_version)
    _stop_active_work(db, agent, "托管 Agent 已暂停接单", actor.id)
    agent.enabled = False
    agent.status = "offline"
    _audit(db, actor, "managed_agent.disable", agent.id, impact)
    db.commit()
    db.refresh(agent)
    return agent


def enable_agent(
    db: Session,
    agent_id: int,
    actor: User,
    *,
    managed_only: bool = True,
) -> Agent:
    agent = _agent_or_404(db, agent_id, managed_only=managed_only)
    agent.enabled = True
    # A heartbeat, not an admin click, is the source of truth for online state.
    agent.status = "offline"
    db.add(AuditLog(
        user_id=actor.id,
        username=actor.username,
        action="managed_agent.enable",
        target_type="agent",
        target_id=agent.id,
        detail="管理员恢复接单；已暂停计划不会自动恢复",
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(
    db: Session,
    agent_id: int,
    actor: User,
    *,
    expected_version: Optional[str] = None,
    require_preview: bool = False,
    managed_only: bool = False,
) -> Dict[str, Any]:
    agent = _agent_or_404(db, agent_id, managed_only=managed_only)
    impact = _snapshot(db, agent, "delete")
    if require_preview:
        _assert_current_version(impact, expected_version)

    _stop_active_work(db, agent, "Agent 已删除", actor.id)
    # Screen data is not historical execution data and must not outlive deletion.
    delete_thumbnail(agent.id)
    agent.thumbnail_updated_at = None
    agent.thumbnail_size = None
    agent.enabled = False
    agent.is_deleted = True
    agent.status = "offline"
    _audit(db, actor, "managed_agent.delete", agent.id, impact)
    db.commit()
    return {
        "message": "Agent 已删除；历史记录保留，同一设备身份不会自动恢复",
        "identity_recovery": impact["identity_recovery"],
    }
