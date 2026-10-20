"""Shared validation and persistence for standard and managed Run creation."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Environment, Run, User
from app.services.script_access import get_accessible_script_or_404
from app.services.script_lifecycle import lock_script_for_lifecycle
from shared.script_contract import validate_params


def ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_run_request(
    db: Session,
    run_user: User,
    script_id: int,
    params: Dict[str, Any],
    environment_id: Optional[int],
    *,
    lock_func=None,
):
    """Lock and validate a script, target-user access, params and environment."""
    (lock_func or lock_script_for_lifecycle)(db, script_id)
    script = get_accessible_script_or_404(db, run_user, script_id, require_active=True)

    if environment_id is not None:
        environment = db.query(Environment).filter(
            Environment.id == environment_id,
            Environment.user_id == run_user.id,
        ).first()
        if not environment:
            raise HTTPException(status_code=404, detail="执行环境不存在")

    if script.config_json:
        try:
            config = json.loads(script.config_json)
        except (TypeError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail="脚本参数配置无效")
        errors = validate_params(config.get("params", []), params, check_paths=False)
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))
    return script


def create_validated_run(
    db: Session,
    *,
    run_user: User,
    script_id: int,
    params: Dict[str, Any],
    environment_id: Optional[int] = None,
    requested_by: Optional[int] = None,
    dispatch_type: str = "standard",
    target_agent_id: Optional[int] = None,
    schedule_id: Optional[int] = None,
    scheduled_for: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    commit: bool = True,
    lock_func=None,
) -> Run:
    script = validate_run_request(
        db, run_user, script_id, params, environment_id, lock_func=lock_func
    )
    run = Run(
        script_id=script.id,
        script_version=script.latest_version,
        user_id=run_user.id,
        status="pending",
        params=json.dumps(params, ensure_ascii=False),
        environment_id=environment_id,
        requested_by=requested_by,
        dispatch_type=dispatch_type,
        target_agent_id=target_agent_id,
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        expires_at=expires_at,
    )
    db.add(run)
    if commit:
        db.commit()
        db.refresh(run)
    else:
        db.flush()
    return run
