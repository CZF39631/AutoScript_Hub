"""User settings API -- stores per-user client configuration."""
import json
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, UserSettings
from app.auth import get_current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    server_url: Optional[str] = None
    script_download_dir: Optional[str] = None
    output_dir: Optional[str] = None
    default_browser_path: Optional[str] = None
    browser_debug_port: Optional[int] = None
    proxy: Optional[str] = None
    pip_index_url: Optional[str] = None
    github_update_repository: Optional[str] = None
    update_channel: Optional[str] = None
    update_manifest_urls: Optional[list[str]] = None


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
    data = json.dumps(req.dict(exclude_none=True), ensure_ascii=False)
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
