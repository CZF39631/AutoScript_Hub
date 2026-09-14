import json
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Run, Script, Issue
from app.auth import get_current_user, require_role
from app.services.audit import write_audit
from app.services.issue_diagnostics import bounded_log, capture_run_log
from app.services.diagnostic_policy import load_diagnostic_policy
from shared.diagnostics import parse_diagnostic_params
from app.services.script_access import accessible_script_ids, accessible_user_ids

router = APIRouter(prefix="/api/issues", tags=["issues"])


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[int] = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=8000)


class IssueResolve(BaseModel):
    resolve_note: str = Field(max_length=8000)


class IssueItem(BaseModel):
    id: int
    run_id: Optional[int] = None
    script_id: Optional[int] = None
    user_id: int
    username: Optional[str] = None
    script_name: Optional[str] = None
    script_version: Optional[int] = None
    log_snapshot_available: bool = False
    title: str
    description: Optional[str] = None
    status: str
    resolve_note: Optional[str] = None
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    run_params: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("", response_model=IssueItem)
def create_issue(
    req: IssueCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policy = load_diagnostic_policy(db)
    script_id = None
    run = None
    secrets = []
    if req.run_id:
        run = db.query(Run).filter(Run.id == req.run_id, Run.is_deleted == False).first()
        if not run:
            raise HTTPException(status_code=404, detail="执行记录不存在")
        if run.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="无权限为该执行记录创建工单")
        script_id = run.script_id
        secrets = policy.secrets(parse_diagnostic_params(run.params))

    issue = Issue(
        run_id=req.run_id,
        script_id=script_id,
        user_id=current_user.id,
        title=policy.text(req.title, "summary", secrets)[:200],
        description=policy.text(req.description, "summary", secrets),
        script_version=run.script_version if run else None,
        log_snapshot=capture_run_log(run.id, secrets, policy) if run else None,
        status="open",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    write_audit(current_user.id, current_user.username, "create_issue",
                target_type="issue", target_id=issue.id, detail="创建工单")
    return _enrich_issue(issue, db, policy)


@router.get("", response_model=list)
def list_issues(
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Issue).filter(Issue.is_deleted == False)
    if current_user.role == "operator":
        q = q.filter(Issue.user_id == current_user.id)
    elif current_user.role == "developer":
        q = q.filter(or_(
            Issue.user_id == current_user.id,
            (
                Issue.script_id.in_(accessible_script_ids(current_user))
                & Issue.user_id.in_(accessible_user_ids(current_user))
            ),
        ))
    if status:
        q = q.filter(Issue.status == status)
    issues = q.order_by(Issue.created_at.desc()).limit(100).all()
    policy = load_diagnostic_policy(db)
    return [_enrich_issue(i, db, policy) for i in issues]


@router.get("/{issue_id}/log")
def get_issue_log(
    issue_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    issue = db.query(Issue).filter(Issue.id == issue_id, Issue.is_deleted == False).first()
    if not issue:
        raise HTTPException(status_code=404, detail="问题工单不存在")
    if current_user.role == "operator" and issue.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="问题工单不存在或无访问权限")
    if current_user.role == "developer" and issue.user_id != current_user.id:
        allowed = db.query(Issue).filter(
            Issue.id == issue.id,
            Issue.script_id.in_(accessible_script_ids(current_user)),
            Issue.user_id.in_(accessible_user_ids(current_user)),
        ).first()
        if not allowed:
            raise HTTPException(status_code=404, detail="问题工单不存在或无访问权限")

    run = db.query(Run).filter(Run.id == issue.run_id).first() if issue.run_id else None
    policy = load_diagnostic_policy(db)
    secrets = policy.secrets(parse_diagnostic_params(run.params)) if run else []
    if issue.log_snapshot is not None:
        return {"log": bounded_log(issue.log_snapshot, secrets, policy)}
    # 旧工单没有快照时保留兼容读取，但同样限制大小并脱敏。
    return {"log": capture_run_log(issue.run_id, secrets, policy) if issue.run_id else ""}


@router.post("/{issue_id}/resolve")
def resolve_issue(
    issue_id: int,
    req: IssueResolve,
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    issue = db.query(Issue).filter(Issue.id == issue_id, Issue.is_deleted == False).first()
    if not issue:
        raise HTTPException(status_code=404, detail="问题工单不存在")
    if current_user.role == "developer" and issue.user_id != current_user.id:
        allowed = db.query(Issue).filter(
            Issue.id == issue.id,
            Issue.script_id.in_(accessible_script_ids(current_user)),
            Issue.user_id.in_(accessible_user_ids(current_user)),
        ).first()
        if not allowed:
            raise HTTPException(status_code=404, detail="问题工单不存在或无访问权限")
    policy = load_diagnostic_policy(db)
    run = db.query(Run).filter(Run.id == issue.run_id).first() if issue.run_id else None
    secrets = policy.secrets(parse_diagnostic_params(run.params)) if run else []
    issue.status = "resolved"
    issue.resolve_note = policy.text(req.resolve_note, "summary", secrets)
    issue.resolved_by = current_user.id
    issue.resolved_at = datetime.now(timezone.utc)
    db.commit()
    write_audit(current_user.id, current_user.username, "resolve_issue",
                target_type="issue", target_id=issue_id, detail="解决工单")
    return {"message": "问题已解决"}


def _enrich_issue(issue, db, policy=None):
    """Add username, script_name, error_msg, run_params to issue dict."""
    policy = policy if policy is not None else load_diagnostic_policy(db)
    user = db.query(User).filter(User.id == issue.user_id).first()
    script = db.query(Script).filter(Script.id == issue.script_id).first() if issue.script_id else None

    item = IssueItem.model_validate(issue)
    item.username = user.display_name if user else "Unknown"
    item.script_name = script.name if script else None
    item.log_snapshot_available = issue.log_snapshot is not None
    secrets = []

    if issue.run_id:
        run = db.query(Run).filter(Run.id == issue.run_id).first()
        if run:
            params = parse_diagnostic_params(run.params)
            secrets = policy.secrets(params)
            item.error_msg = policy.text(run.error_msg, "summary", secrets)
            item.run_params = json.dumps(policy.params(params, secrets), ensure_ascii=False)
            if item.script_version is None:
                item.script_version = run.script_version

    item.title = policy.text(item.title, "summary", secrets)
    item.description = policy.text(item.description, "summary", secrets)
    item.resolve_note = policy.text(item.resolve_note, "summary", secrets)
    return item
