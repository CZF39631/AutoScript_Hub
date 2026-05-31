"""User settings API -- stores per-user client configuration."""
import json
import os
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, Text, ForeignKey
from app.database import get_db, engine, Base
from app.models import User
from app.auth import get_current_user
from app.config import PROJECT_ROOT


class UserSettings(Base):
    __tablename__ = "user_settings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    settings_json = Column(Text, nullable=False, default="{}")


Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    server_url: Optional[str] = None
    script_download_dir: Optional[str] = None
    output_dir: Optional[str] = None
    default_browser_path: Optional[str] = None
    browser_debug_port: Optional[int] = None
    proxy: Optional[str] = None


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
    except Exception:
        return {}


@router.put("")
def update_settings(
    req: SettingsPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    data = json.dumps(req.dict(), ensure_ascii=False)
    if row:
        row.settings_json = data
    else:
        row = UserSettings(user_id=current_user.id, settings_json=data)
        db.add(row)
    db.commit()

    # Sync to client_config.json
    config_path = os.path.join(PROJECT_ROOT, "client_config.json")
    try:
        client_cfg = {}
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                client_cfg = json.load(f)
        updates = req.dict(exclude_none=True)
        client_cfg.update(updates)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(client_cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return {"message": "Settings saved"}


@router.delete("")
def reset_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    if row:
        db.delete(row)
        db.commit()

    config_path = os.path.join(PROJECT_ROOT, "client_config.json")
    try:
        if os.path.isfile(config_path):
            os.remove(config_path)
    except Exception:
        pass

    return {"message": "Settings reset"}


@router.get("/client-version")
def client_version():
    """Return current client version info for auto-update checks."""
    config_path = os.path.join(PROJECT_ROOT, "config.json")
    version = "1.0.0"
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            version = cfg.get("client_version", version)
        except Exception:
            pass
    return {"version": version}
