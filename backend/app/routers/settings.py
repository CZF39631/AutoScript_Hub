"""Per-user client settings and administrator-only global server settings."""
import json
import re
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ServerSettings, User, UserSettings
from app.auth import get_current_user, require_role
from app.services.audit import write_audit
from app.services.diagnostic_policy import DiagnosticPolicy, load_diagnostic_policy

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    server_url: Optional[str] = None
    script_download_dir: Optional[str] = None
    output_dir: Optional[str] = None
    default_browser_path: Optional[str] = None
    browser_debug_port: Optional[int] = None
    proxy: Optional[str] = None
    pip_index_url: Optional[str] = None
    gitee_update_repository: Optional[str] = None
    github_update_repository: Optional[str] = None
    update_channel: Optional[str] = None
    update_manifest_urls: Optional[list[str]] = None


_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ServerUpdateSettingsPayload(BaseModel):
    enabled: bool = False
    outbound_proxy: Optional[str] = Field(default=None, max_length=2048)
    github_repository: str = Field(default="CZF39631/AutoScript_Hub", min_length=3, max_length=255)
    interval_hours: int = Field(default=6, ge=1, le=168)

    @field_validator("outbound_proxy")
    @classmethod
    def validate_proxy(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("代理 URL 不能包含控制字符")
        if value != value.strip() or any(char.isspace() for char in value):
            raise ValueError("代理 URL 不能包含空白字符")
        parsed = urlsplit(value)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("代理 URL 端口无效") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("代理必须是有效的 http/https URL")
        return value

    @field_validator("github_repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        value = value.strip()
        if not _REPOSITORY_PATTERN.fullmatch(value):
            raise ValueError("GitHub 仓库必须使用 owner/repository 格式")
        return value


class DiagnosticSettingsUpdate(DiagnosticPolicy):
    acknowledge_risk: bool = False


@router.get("/diagnostics", response_model=DiagnosticPolicy)
def get_diagnostic_settings(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return load_diagnostic_policy(db)


@router.put("/diagnostics", response_model=DiagnosticPolicy)
def update_diagnostic_settings(
    req: DiagnosticSettingsUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = _server_settings(db)
    previous_json = row.diagnostic_policy_json
    previous = load_diagnostic_policy(db)
    policy = DiagnosticPolicy.model_validate(req.model_dump(exclude={"acknowledge_risk"}))
    if policy.weakens(previous) and not req.acknowledge_risk:
        raise HTTPException(status_code=409, detail="降低脱敏保护可能暴露凭据和业务数据，请明确确认风险")
    updated = db.query(ServerSettings).filter(
        ServerSettings.id == 1,
        ServerSettings.diagnostic_policy_json == previous_json,
    ).update({
        ServerSettings.diagnostic_policy_json: policy.model_dump_json(),
        ServerSettings.updated_by: current_user.id,
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="诊断配置已被其他操作修改，请重新读取后保存")
    db.commit()
    changed = [field for field, value in policy.model_dump().items() if previous.model_dump()[field] != value]
    write_audit(
        current_user.id, current_user.username, "update_diagnostic_settings",
        target_type="server_settings", target_id=1,
        detail="changed fields: " + (", ".join(changed) or "none"),
    )
    return policy


class ServerUpdateSettingsResponse(ServerUpdateSettingsPayload):
    model_config = ConfigDict(from_attributes=True)


def _server_settings(db: Session) -> ServerSettings:
    row = db.query(ServerSettings).filter(ServerSettings.id == 1).first()
    if row is None:
        row = ServerSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("")
def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    if not row:
        return {}
    try:
        return json.loads(row.settings_json)
    except (json.JSONDecodeError, OSError):
        return {}


@router.put("")
def update_settings(
    req: SettingsPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    data = json.dumps(req.model_dump(exclude_none=True), ensure_ascii=False)
    if row:
        row.settings_json = data
    else:
        row = UserSettings(user_id=current_user.id, settings_json=data)  # type: ignore[call-arg]
        db.add(row)
    db.commit()

    return {"message": "设置已保存"}


@router.delete("")
def reset_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    if row:
        db.delete(row)
        db.commit()

    return {"message": "设置已重置"}


@router.get("/server-update", response_model=ServerUpdateSettingsResponse)
def get_server_update_settings(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return _server_settings(db)


@router.put("/server-update", response_model=ServerUpdateSettingsResponse)
def update_server_update_settings(
    req: ServerUpdateSettingsPayload,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = _server_settings(db)
    changed_fields = []
    for field, value in req.model_dump().items():
        if getattr(row, field) != value:
            changed_fields.append(field)
            setattr(row, field, value)
    row.updated_by = current_user.id
    db.commit()
    db.refresh(row)

    # Record names only: proxy credentials and all other values stay out of audit logs.
    write_audit(
        current_user.id,
        current_user.username,
        "update_server_update_settings",
        target_type="server_settings",
        target_id=1,
        detail="changed fields: " + (", ".join(changed_fields) or "none"),
    )
    # Wake the independent downloader so enabling/changing settings takes effect now.
    from app.server_update_cache import wake_server_update_cache
    wake_server_update_cache()
    return row
