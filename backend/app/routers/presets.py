"""Parameter presets API (design §5.3).

Two kinds of presets:
  - Developer presets: stored in script.config_json under "presets" key (read-only for operators).
  - Personal presets: stored in user_presets table, owned by individual operators.

Routes:
  GET    /api/scripts/{script_id}/presets        → { developer: [...], personal: [...] }
  POST   /api/scripts/{script_id}/presets        → create personal preset for current user
  PUT    /api/presets/{preset_id}                → update own personal preset
  DELETE /api/presets/{preset_id}                → delete own personal preset
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Script, UserPreset
from app.auth import get_current_user

logger = logging.getLogger(__name__)

# Router without prefix — mixes /api/scripts/{id}/presets and /api/presets/{id} paths
router = APIRouter(tags=["presets"])


class PresetItem(BaseModel):
    """A preset is a named bag of param values that partially fills the script's config form."""
    id: Optional[int] = None       # None for developer presets (not persisted as a row)
    name: str
    values: Dict[str, Any]
    source: str                    # "developer" | "personal"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class PresetBundle(BaseModel):
    developer: List[PresetItem]
    personal: List[PresetItem]


class PresetCreate(BaseModel):
    name: str
    values: Dict[str, Any]


class PresetUpdate(BaseModel):
    name: Optional[str] = None
    values: Optional[Dict[str, Any]] = None


def _row_to_item(row: UserPreset) -> PresetItem:
    try:
        values = json.loads(row.values_json) if row.values_json else {}
    except (json.JSONDecodeError, ValueError):
        values = {}
    return PresetItem(
        id=row.id,
        name=row.name,
        values=values,
        source="personal",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _developer_presets(script: Script) -> List[PresetItem]:
    """Extract developer-defined presets from script's config_json."""
    if not script.config_json:
        return []
    try:
        config = json.loads(script.config_json)
    except (json.JSONDecodeError, ValueError):
        return []
    items = []
    for p in config.get("presets", []) or []:
        if not isinstance(p, dict):
            continue
        items.append(PresetItem(
            name=str(p.get("name", "Preset")),
            values=p.get("values", {}) or {},
            source="developer",
        ))
    return items


@router.get("/api/scripts/{script_id}/presets", response_model=PresetBundle)
def list_presets(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return both developer presets (read-only) and current user's personal presets."""
    script = db.query(Script).filter(
        Script.id == script_id, Script.is_deleted == False
    ).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")

    personal_rows = db.query(UserPreset).filter(
        UserPreset.user_id == current_user.id,
        UserPreset.script_id == script_id,
    ).order_by(UserPreset.created_at).all()

    return PresetBundle(
        developer=_developer_presets(script),
        personal=[_row_to_item(r) for r in personal_rows],
    )


@router.post("/api/scripts/{script_id}/presets", response_model=PresetItem)
def create_preset(
    script_id: int,
    req: PresetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save current user's personal preset for a script."""
    script = db.query(Script).filter(
        Script.id == script_id, Script.is_deleted == False
    ).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="预设名称为必填项")

    # Enforce uniqueness per (user, script, name)
    existing = db.query(UserPreset).filter(
        UserPreset.user_id == current_user.id,
        UserPreset.script_id == script_id,
        UserPreset.name == req.name.strip(),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="预设名称已存在")

    row = UserPreset(
        user_id=current_user.id,
        script_id=script_id,
        name=req.name.strip(),
        values_json=json.dumps(req.values, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_item(row)


@router.put("/api/presets/{preset_id}", response_model=PresetItem)
def update_preset(
    preset_id: int,
    req: PresetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update own personal preset. Operators cannot edit other users' presets."""
    row = db.query(UserPreset).filter(
        UserPreset.id == preset_id,
        UserPreset.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="预设不存在")

    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="预设名称不能为空")
        # Check name conflict within same (user, script)
        conflict = db.query(UserPreset).filter(
            UserPreset.user_id == current_user.id,
            UserPreset.script_id == row.script_id,
            UserPreset.name == new_name,
            UserPreset.id != preset_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="预设名称已存在")
        row.name = new_name
    if req.values is not None:
        row.values_json = json.dumps(req.values, ensure_ascii=False)

    db.commit()
    db.refresh(row)
    return _row_to_item(row)


@router.delete("/api/presets/{preset_id}")
def delete_preset(
    preset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserPreset).filter(
        UserPreset.id == preset_id,
        UserPreset.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="预设不存在")
    db.delete(row)
    db.commit()
    return {"message": "预设已删除"}
