import json
from typing import Any, Dict, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Environment
from app.auth import get_current_user
from app.services.audit import write_audit

router = APIRouter(prefix="/api/environments", tags=["environments"])


class EnvCreate(BaseModel):
    name: str
    browser_port: Optional[int] = None
    browser_path: Optional[str] = None
    python_version: Optional[str] = None
    venv_path: Optional[str] = None
    venv_status: Optional[str] = "none"
    python_executable: Optional[str] = None
    output_dir: Optional[str] = None
    proxy: Optional[str] = None
    extra_env: Optional[Dict[str, Any]] = None
    is_default: bool = False


class EnvUpdate(BaseModel):
    name: Optional[str] = None
    browser_port: Optional[int] = None
    browser_path: Optional[str] = None
    python_version: Optional[str] = None
    venv_path: Optional[str] = None
    venv_status: Optional[str] = None
    python_executable: Optional[str] = None
    output_dir: Optional[str] = None
    proxy: Optional[str] = None
    extra_env: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None


class EnvItem(BaseModel):
    id: int
    user_id: int
    name: str
    browser_port: Optional[int] = None
    browser_path: Optional[str] = None
    python_version: Optional[str] = None
    venv_path: Optional[str] = None
    venv_status: Optional[str] = "none"
    python_executable: Optional[str] = None
    output_dir: Optional[str] = None
    proxy: Optional[str] = None
    extra_env: Optional[Dict[str, Any]] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


def _parse_extra(env):
    """Parse extra_env JSON string to dict for response."""
    item = EnvItem.from_orm(env)
    if isinstance(env.extra_env, str):
        try:
            item.extra_env = json.loads(env.extra_env)
        except (json.JSONDecodeError, ValueError):
            item.extra_env = {}
    return item


@router.get("", response_model=list)
def list_environments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    envs = db.query(Environment).filter(Environment.user_id == current_user.id).order_by(Environment.created_at).all()
    return [_parse_extra(e) for e in envs]


@router.post("", response_model=EnvItem)
def create_environment(
    req: EnvCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.is_default:
        db.query(Environment).filter(
            Environment.user_id == current_user.id, Environment.is_default == True
        ).update({"is_default": False})

    env = Environment(
        user_id=current_user.id,
        name=req.name,
        browser_port=req.browser_port,
        browser_path=req.browser_path,
        python_version=req.python_version,
        venv_path=req.venv_path,
        venv_status=req.venv_status or "none",
        python_executable=req.python_executable,
        output_dir=req.output_dir,
        proxy=req.proxy,
        extra_env=json.dumps(req.extra_env, ensure_ascii=False) if req.extra_env else None,
        is_default=req.is_default,
    )
    db.add(env)
    db.commit()
    db.refresh(env)
    write_audit(current_user.id, current_user.username, "create_env",
                target_type="environment", target_id=env.id, detail=req.name)
    return _parse_extra(env)


@router.put("/{env_id}", response_model=EnvItem)
def update_environment(
    env_id: int,
    req: EnvUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    env = db.query(Environment).filter(
        Environment.id == env_id, Environment.user_id == current_user.id
    ).first()
    if not env:
        raise HTTPException(status_code=404, detail="运行环境不存在")

    if req.is_default:
        db.query(Environment).filter(
            Environment.user_id == current_user.id, Environment.is_default == True
        ).update({"is_default": False})

    for field in ["name", "browser_port", "browser_path", "python_version",
                   "venv_path", "venv_status", "python_executable",
                   "output_dir", "proxy", "is_default"]:
        val = getattr(req, field, None)
        if val is not None:
            setattr(env, field, val)
    if req.extra_env is not None:
        env.extra_env = json.dumps(req.extra_env, ensure_ascii=False)

    db.commit()
    db.refresh(env)
    return _parse_extra(env)


@router.delete("/{env_id}")
def delete_environment(
    env_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    env = db.query(Environment).filter(
        Environment.id == env_id, Environment.user_id == current_user.id
    ).first()
    if not env:
        raise HTTPException(status_code=404, detail="运行环境不存在")
    db.delete(env)
    db.commit()
    write_audit(current_user.id, current_user.username, "delete_env",
                target_type="environment", target_id=env_id, detail=env.name)
    return {"message": "已删除"}


@router.get("/default", response_model=EnvItem)
def get_default_environment(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    env = db.query(Environment).filter(
        Environment.user_id == current_user.id, Environment.is_default == True
    ).first()
    if not env:
        raise HTTPException(status_code=404, detail="未设置默认环境")
    return _parse_extra(env)


@router.get("/{env_id}", response_model=EnvItem)
def get_environment(
    env_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    env = db.query(Environment).filter(
        Environment.id == env_id, Environment.user_id == current_user.id
    ).first()
    if not env:
        raise HTTPException(status_code=404, detail="运行环境不存在")
    return _parse_extra(env)
