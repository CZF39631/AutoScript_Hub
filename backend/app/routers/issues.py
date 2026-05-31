from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Run, Script, Issue
from app.auth import get_current_user, require_role
from app.services.audit import write_audit

router = APIRouter(prefix="/api/issues", tags=["issues"])


class IssueCreate(BaseModel):
    run_id: Optional[int] = None
    title: str
    description: Optional[str] = None


class IssueResolve(BaseModel):
    resolve_note: str


class IssueItem(BaseModel):
    id: int
    run_id: Optional[int] = None
    script_id: Optional[int] = None
    user_id: int
    username: Optional[str] = None
    script_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    resolve_note: Optional[str] = None
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    run_params: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


@router.post("", response_model=IssueItem)
def create_issue(
    req: IssueCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    script_id = None
    if req.run_id:
        run = db.query(Run).filter(Run.id == req.run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        script_id = run.script_id

    issue = Issue(
        run_id=req.run_id,
        script_id=script_id,
        user_id=current_user.id,
        title=req.title,
        description=req.description,
        status="open",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    write_audit(current_user.id, current_user.username, "create_issue",
                target_type="issue", target_id=issue.id, detail=req.title)
    return _enrich_issue(issue, db)


@router.get("", response_model=list)
def list_issues(
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Issue).filter(Issue.is_deleted == False)
    if current_user.role == "operator":
        q = q.filter(Issue.user_id == current_user.id)
    if status:
        q = q.filter(Issue.status == status)
    issues = q.order_by(Issue.created_at.desc()).limit(100).all()
    return [_enrich_issue(i, db) for i in issues]


@router.get("/{issue_id}/log")
def get_issue_log(
    issue_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.config import LOGS_DIR
    import os
    issue = db.query(Issue).filter(Issue.id == issue_id, Issue.is_deleted == False).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if current_user.role == "operator" and issue.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if not issue.run_id:
        return {"log": ""}

    log_file = os.path.join(LOGS_DIR, "{}.log".format(issue.run_id))
    if not os.path.isfile(log_file):
        return {"log": ""}
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        return {"log": f.read()}


@router.post("/{issue_id}/resolve")
def resolve_issue(
    issue_id: int,
    req: IssueResolve,
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    issue = db.query(Issue).filter(Issue.id == issue_id, Issue.is_deleted == False).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue.status = "resolved"
    issue.resolve_note = req.resolve_note
    issue.resolved_by = current_user.id
    issue.resolved_at = datetime.utcnow()
    db.commit()
    write_audit(current_user.id, current_user.username, "resolve_issue",
                target_type="issue", target_id=issue_id, detail=issue.title)
    return {"message": "Issue resolved"}


def _enrich_issue(issue, db):
    """Add username, script_name, error_msg, run_params to issue dict."""
    user = db.query(User).filter(User.id == issue.user_id).first()
    script = db.query(Script).filter(Script.id == issue.script_id).first() if issue.script_id else None

    item = IssueItem.from_orm(issue)
    item.username = user.display_name if user else "Unknown"
    item.script_name = script.name if script else None

    if issue.run_id:
        run = db.query(Run).filter(Run.id == issue.run_id).first()
        if run:
            item.error_msg = run.error_msg
            item.run_params = run.params

    return item
