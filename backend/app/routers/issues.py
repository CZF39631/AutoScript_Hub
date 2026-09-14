import json
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Run, Script, Issue
from app.auth import get_current_user, require_role
from app.services.audit import write_audit
from app.diagnostic_models import IssueDiagnostic  # register metadata
from app.services.issue_diagnostics import bounded_log, capture_run_log, build_snapshot, save_snapshot, read_snapshot, MAX_DIAGNOSTIC_BYTES
from app.services.diagnostic_policy import load_diagnostic_policy
from shared.diagnostics import parse_diagnostic_params
from app.services.script_access import accessible_script_ids, accessible_user_ids

class BoundedIssueRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method in {'POST', 'PUT', 'PATCH'}:
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_DIAGNOSTIC_BYTES:
                        raise HTTPException(413, '请求超过 192 KiB 上限')
                    body.extend(chunk)
                # Starlette Request.body() uses this cache; reject before JSON decoding.
                request._body = bytes(body)
            try:
                response = await handler(request)
            except RequestValidationError:
                # 1.2.4 UI renders detail directly; structured Pydantic errors
                # can crash that UI and echo input. Keep a safe string contract.
                raise HTTPException(422, '工单输入无效：标题须为1–200字符，描述或处理说明不超过8000字符；请检查诊断选项')
            response.headers['Cache-Control'] = 'no-store'
            return response
        return bounded


router = APIRouter(prefix="/api/issues", tags=["issues"], route_class=BoundedIssueRoute)


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[int] = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=8000)
    diagnostics: Optional[dict] = None
    diagnostics_consent: bool = Field(default=False, strict=True)
    include_run_log: bool = Field(default=False, strict=True)
    include_run_summary: bool = Field(default=False, strict=True)


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
    diagnostic_state: str = 'legacy'
    diagnostic_metadata: dict = Field(default_factory=dict)
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


def _validate_request(req, current_user, db):
    if len(req.model_dump_json().encode('utf-8')) > MAX_DIAGNOSTIC_BYTES:
        raise HTTPException(413, '诊断内容超过 192 KiB 上限')
    if (req.diagnostics is not None or req.include_run_log or req.include_run_summary) and not req.diagnostics_consent:
        raise HTTPException(422, '附带诊断需要明确确认')
    if req.diagnostics is not None:
        allowed = {'client_version', 'agent_version', 'agent_id', 'online', 'system', 'machine', 'python_version', 'collection_state', 'application_logs'}
        if set(req.diagnostics) - allowed or not isinstance(req.diagnostics.get('application_logs', {}), dict):
            raise HTTPException(422, '诊断字段无效')
        for key, value in req.diagnostics.items():
            if key == 'application_logs':
                if set(value) - {'agent', 'desktop'} or any(not isinstance(v, str) for v in value.values()):
                    raise HTTPException(422, '应用日志字段无效')
            elif key == 'online':
                if type(value) is not bool:
                    raise HTTPException(422, '在线状态字段无效')
            elif not isinstance(value, str) or len(value) > 200:
                raise HTTPException(422, '诊断摘要字段无效')
    if (req.include_run_log or req.include_run_summary) and not req.run_id:
        raise HTTPException(422, '执行日志必须关联执行记录')
    if not req.run_id:
        return None
    run = db.query(Run).filter(Run.id == req.run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(404, '执行记录不存在')
    if run.user_id != current_user.id and current_user.role != 'admin':
        raise HTTPException(403, '无权限为该执行记录创建工单')
    return run


def _request_snapshot(run, req, policy):
    # 未选择摘要时不保存 Run 参数/错误；仅用其已知敏感值保护所选日志。
    payload = build_snapshot(run, req.diagnostics, policy, include_summary=req.include_run_summary)
    payload['script_version'] = run.script_version if run else None
    return payload


@router.post('/preview')
def preview_issue(req: IssueCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _validate_request(req, current_user, db)
    policy = load_diagnostic_policy(db)
    payload = _request_snapshot(run, req, policy)
    secrets = policy.secrets(parse_diagnostic_params(run.params)) if run else []
    payload.update(title=policy.text(req.title, 'summary', secrets), description=policy.text(req.description, 'summary', secrets), run_log=capture_run_log(run.id, secrets, policy) if run and req.include_run_log else '')
    size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    if size > MAX_DIAGNOSTIC_BYTES:
        raise HTTPException(413, '诊断预览超过 192 KiB 上限')
    return {'preview': payload, 'size_bytes': size, 'notice': '所选内容已发送服务器进行预览；尚未创建工单。'}


@router.post("", response_model=IssueItem)
def create_issue(
    req: IssueCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_request(req, current_user, db)
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
        log_snapshot=capture_run_log(run.id, secrets, policy) if run and req.include_run_log else None,
        status="open",
    )
    db.add(issue)
    db.flush()
    payload = _request_snapshot(run, req, policy)
    if len(json.dumps({**payload, 'run_log': issue.log_snapshot or ''}, ensure_ascii=False).encode('utf-8')) > MAX_DIAGNOSTIC_BYTES:
        db.rollback()
        raise HTTPException(413, '诊断内容超过 192 KiB 上限')
    save_snapshot(db, issue, payload, policy, state='collected' if req.diagnostics_consent else 'not_collected')
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

    policy = load_diagnostic_policy(db)
    snapshot = read_snapshot(db, issue, policy)
    if snapshot is not None:
        if snapshot['state'] == 'expired':
            return {'log': '', 'state': 'expired'}
        return {'log': bounded_log(issue.log_snapshot or '', policy.secrets(snapshot['params']), policy)}
    run = db.query(Run).filter(Run.id == issue.run_id).first() if issue.run_id else None
    secrets = policy.secrets(parse_diagnostic_params(run.params)) if run else []
    if issue.log_snapshot is not None:
        return {"log": bounded_log(issue.log_snapshot, secrets, policy)}
    # 旧工单没有快照时保留兼容读取，但同样限制大小并脱敏。
    return {"log": capture_run_log(issue.run_id, secrets, policy) if issue.run_id else ""}


@router.get('/{issue_id}/diagnostics')
def download_issue_diagnostics(issue_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Reuse exactly the log endpoint's issue-level permission check before reading diagnostics.
    log = get_issue_log(issue_id, current_user, db)
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    snapshot = read_snapshot(db, issue, load_diagnostic_policy(db))
    if snapshot is None:
        raise HTTPException(404, '历史工单未采集诊断')
    if snapshot['state'] == 'expired':
        raise HTTPException(410, '诊断已过期，内容已不可下载')
    from fastapi.responses import Response
    payload = json.dumps({**snapshot, 'run_log': log['log']}, ensure_ascii=False)
    if len(payload.encode('utf-8')) > MAX_DIAGNOSTIC_BYTES:
        raise HTTPException(413, '诊断内容超过下载上限')
    return Response(payload, media_type='application/json', headers={'Content-Disposition': f'attachment; filename="issue-{issue_id}-diagnostics.json"', 'Cache-Control': 'no-store'})


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

    snapshot = read_snapshot(db, issue, policy)
    if snapshot is not None:
        item.script_version = snapshot.get('script_version', issue.script_version)
        item.diagnostic_state = snapshot['state']
        item.diagnostic_metadata = snapshot.get('metadata', {})
        item.error_msg = snapshot.get('error_msg')
        item.run_params = json.dumps(snapshot.get('params', {}), ensure_ascii=False)
        item.log_snapshot_available = snapshot['state'] != 'expired' and issue.log_snapshot is not None
        secrets = policy.secrets(snapshot.get('params', {}))
    elif issue.run_id:
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
