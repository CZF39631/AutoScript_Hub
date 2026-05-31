from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models import User, AuditLog
from app.auth import require_role

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogItem(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    detail: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


@router.get("", response_model=list)
def list_audit_logs(
    action: Optional[str] = None,
    username: Optional[str] = None,
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
    return q.offset(offset).limit(limit).all()
