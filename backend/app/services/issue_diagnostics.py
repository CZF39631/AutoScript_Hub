"""工单保存有界策略快照与用户确认的白名单客户端诊断。"""

from pathlib import Path
import json
import os
import stat
from datetime import datetime, timezone, timedelta
from app.diagnostic_models import IssueDiagnostic
from shared.diagnostics import parse_diagnostic_params

MAX_DIAGNOSTIC_BYTES = 192 * 1024


def build_snapshot(run, client, policy, include_summary=True):
    params = parse_diagnostic_params(run.params) if run else {}
    secrets = policy.secrets(params)
    metadata = {}
    for key in ('client_version', 'agent_version', 'agent_id', 'online', 'system', 'machine', 'python_version', 'collection_state'):
        value = (client or {}).get(key)
        if isinstance(value, (str, bool)):
            metadata[key] = policy.text(value[:200], 'summary', secrets) if isinstance(value, str) else value
    return {
        'script_version': run.script_version if run else None,
        'params': policy.params(params, secrets) if include_summary else {},
        'error_msg': bounded_text(policy.text(run.error_msg, 'summary', secrets), 16 * 1024) if run and include_summary else None,
        'metadata': metadata,
        'application_logs': {key: bounded_log(value, secrets, policy) for key, value in (client or {}).get('application_logs', {}).items() if key in ('agent', 'desktop') and isinstance(value, str)},
    }


def save_snapshot(db, issue, payload, policy, state='collected'):
    if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > MAX_DIAGNOSTIC_BYTES:
        from fastapi import HTTPException
        raise HTTPException(413, '脱敏后的诊断内容超过保存上限')
    now = datetime.now(timezone.utc)
    db.add(IssueDiagnostic(issue_id=issue.id, state=state, payload_json=json.dumps(payload, ensure_ascii=False), created_at=now, expires_at=now + timedelta(days=policy.retention_days)))


def cleanup_issue_diagnostics(db, now=None):
    from app.models import Issue
    now = now or datetime.now(timezone.utc)
    rows = (db.query(IssueDiagnostic)
            .filter(IssueDiagnostic.state != 'expired', IssueDiagnostic.expires_at <= now)
            .order_by(IssueDiagnostic.expires_at, IssueDiagnostic.issue_id)
            .limit(500).all())
    for row in rows:
        row.state = 'expired'
        row.payload_json = '{}'
        issue = db.query(Issue).filter(Issue.id == row.issue_id).first()
        if issue:
            issue.log_snapshot = ''
    db.flush()
    return len(rows)


def read_snapshot(db, issue, policy):
    row = db.query(IssueDiagnostic).filter(IssueDiagnostic.issue_id == issue.id).first()
    if row is None:
        return None
    expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if row.state == 'expired' or expiry <= datetime.now(timezone.utc):
        return {'state': 'expired', 'metadata': {}, 'params': {}, 'error_msg': None, 'application_logs': {}}
    payload = json.loads(row.payload_json)
    secrets = policy.secrets(payload.get('params', {}))
    payload['params'] = policy.params(payload.get('params', {}), secrets)
    payload['error_msg'] = policy.text(payload.get('error_msg'), 'summary', secrets)
    payload['metadata'] = {k: policy.text(v, 'summary', secrets) if isinstance(v, str) else v for k, v in payload.get('metadata', {}).items()}
    payload['application_logs'] = {k: bounded_log(v, secrets, policy) for k, v in payload.get('application_logs', {}).items()}
    payload['state'] = row.state
    return payload

from app.services.diagnostic_policy import DiagnosticPolicy

MAX_LOG_BYTES = 64 * 1024
MAX_LOG_LINES = 500
TRUNCATED = "[日志已截断，仅保留末尾片段]\n"


def bounded_text(text, limit):
    return text.encode('utf-8')[:limit].decode('utf-8', errors='ignore') if text is not None else None


def bounded_log(text, secrets=(), policy=None):
    policy = policy if policy is not None else DiagnosticPolicy()
    cleaned = policy.text(text, "logs", secrets)
    lines = cleaned.splitlines(keepends=True)
    truncated = len(lines) > MAX_LOG_LINES
    cleaned = "".join(lines[-(MAX_LOG_LINES - 1 if truncated else MAX_LOG_LINES):])
    encoded = cleaned.encode("utf-8")
    limit = MAX_LOG_BYTES - len(TRUNCATED.encode("utf-8"))
    if len(encoded) > limit:
        # 从完整行开始，避免返回被截断的凭据或私钥标记。
        tail = encoded[-limit:]
        cleaned = tail.split(b"\n", 1)[1].decode("utf-8", errors="replace") if b"\n" in tail else ""
        truncated = True
    return bounded_text((TRUNCATED if truncated else "") + cleaned, MAX_LOG_BYTES)


def capture_run_log(run_id, secrets=(), policy=None):
    from app.config import LOGS_DIR

    path = Path(LOGS_DIR) / f"{int(run_id)}.log"
    try:
        if path.is_symlink() or Path(LOGS_DIR).is_symlink() or not path.is_file():
            return ''
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return ''
            size = stream.seek(0, 2)
            start = max(0, size - MAX_LOG_BYTES)
            stream.seek(start)
            raw = stream.read(MAX_LOG_BYTES)
    except OSError:
        return ""
    if start:
        # 丢弃尾部读取切中的首行，不把半截密码作为普通文字返回。
        raw = raw.split(b"\n", 1)[1] if b"\n" in raw else b""
    text = raw.decode("utf-8", errors="replace")
    return bounded_log((TRUNCATED if start else "") + text, secrets, policy)
