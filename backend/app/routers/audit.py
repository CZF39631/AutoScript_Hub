from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.database import get_db
from app.models import Agent, User, AuditLog
from app.auth import require_role

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogItem(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    detail: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[AuditLogItem])
def list_audit_logs(
    action: Optional[str] = None,
    username: Optional[str] = None,
    target_type: Optional[str] = Query(default=None, max_length=50),
    target_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        q = q.filter(AuditLog.action == action)
    if username:
        q = q.filter(AuditLog.username.contains(username))
    if target_type:
        q = q.filter(AuditLog.target_type == target_type)
    if target_id is not None:
        q = q.filter(AuditLog.target_id == target_id)
    rows = q.offset(offset).limit(limit).all()
    agent_ids = {
        row.target_id for row in rows
        if row.target_type == "agent" and row.target_id is not None
    }
    agent_names = dict(db.query(Agent.id, Agent.machine_name).filter(
        Agent.id.in_(agent_ids)
    ).all()) if agent_ids else {}
    return [AuditLogItem.model_validate(row).model_copy(update={
        "target_name": agent_names.get(row.target_id) if row.target_type == "agent" else None,
    }) for row in rows]
