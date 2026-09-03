import json
import logging
import os
import shutil
import tempfile
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Script, ScriptVersion, UserScript
from app.schemas import GroupBrief, ScriptBrief, ScriptDetail, ScriptGroupUpdate, ScriptVersionBrief
from app.auth import get_current_user, require_role
from app.services.script_storage import save_script_file
from app.services.audit import write_audit
from app.services.groups import get_or_create_default_group
from app.services.script_access import (
    active_group_ids_for_user,
    assignable_groups,
    can_manage_script,
    get_accessible_script_or_404,
    get_manageable_script_or_404,
    restrict_script_query,
)
from shared.script_contract import validate_script

router = APIRouter(prefix="/api/scripts", tags=["scripts"])
logger = logging.getLogger(__name__)


def _safe_upload_name(filename: str) -> str:
    """Return a plain filename and reject paths supplied by multipart clients."""
    normalized = filename.replace("\\", "/")
    safe_name = normalized.rsplit("/", 1)[-1]
    if not safe_name or safe_name in (".", "..") or normalized != safe_name:
        raise HTTPException(status_code=400, detail="文件名不能包含路径")
    return safe_name


def _validated_upload(path):
    report = validate_script(path, strict=False)
    if report.errors:
        first = report.errors[0]
        raise HTTPException(
            status_code=400,
            detail={"code": first.code, "message": first.message, "path": first.path},
        )
    for warning in report.warnings:
        logger.warning("Script compatibility warning %s: %s", warning.code, warning.message)
    return report.config


def _response_groups(script, db, current_user):
    groups = list(script.groups)
    if current_user.role != "admin":
        allowed_ids = active_group_ids_for_user(db, current_user)
        groups = [
            group for group in groups
            if group.id in allowed_ids and group.status == "active" and not group.is_deleted
        ]
    return [GroupBrief.model_validate(group) for group in groups]


def _script_brief_from_orm(script, db, current_user):
    if hasattr(ScriptBrief, "model_validate"):
        item = ScriptBrief.model_validate(script)
    else:
        item = ScriptBrief.from_orm(script)
    item.groups = _response_groups(script, db, current_user)
    item.can_manage = can_manage_script(db, current_user, script)
    item.can_manage_groups = current_user.role == "admin"
    return item


def _script_detail_from_orm(script, db, current_user):
    item = ScriptDetail.model_validate(script)
    item.groups = _response_groups(script, db, current_user)
    item.can_manage = can_manage_script(db, current_user, script)
    item.can_manage_groups = current_user.role == "admin"
    return item


def _parse_group_ids(raw):
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="group_ids 必须是 JSON 数组")
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise HTTPException(status_code=400, detail="group_ids 必须是整数数组")
    return value


def _upload_groups(db, current_user, raw_group_ids):
    group_ids = _parse_group_ids(raw_group_ids)
    if group_ids is None:
        if current_user.role == "admin":
            group_ids = [get_or_create_default_group(db, current_user.id).id]
        else:
            group_ids = sorted(active_group_ids_for_user(db, current_user))
    return assignable_groups(db, current_user, group_ids, allow_empty=True)


@router.get("", response_model=List[ScriptBrief])
def list_scripts(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Script).filter(Script.is_deleted == False, Script.status == "active")
    q = restrict_script_query(q, current_user)
    if category:
        q = q.filter(Script.category == category)

    # “我的脚本”只表示当前用户主动安装的脚本。管理权限与安装归属分离。
    installed_ids = [us.script_id for us in
                     db.query(UserScript).filter(UserScript.user_id == current_user.id).all()]
    if not installed_ids:
        return []
    q = q.filter(Script.id.in_(installed_ids))
    scripts = q.order_by(Script.updated_at.desc()).all()
    return [_script_brief_from_orm(script, db, current_user) for script in scripts]


@router.get("/marketplace", response_model=List[ScriptBrief])
def list_marketplace(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Script).filter(Script.is_deleted == False, Script.status == "active")
    q = restrict_script_query(q, current_user)
    if category:
        q = q.filter(Script.category == category)
    scripts = q.order_by(Script.updated_at.desc()).all()

    installed_ids = {us.script_id for us in
                     db.query(UserScript).filter(UserScript.user_id == current_user.id).all()}

    result = []
    for s in scripts:
        item = _script_brief_from_orm(s, db, current_user)
        item.installed = s.id in installed_ids
        result.append(item)
    return result


@router.get("/manageable", response_model=List[ScriptBrief])
def list_manageable_scripts(
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    query = db.query(Script).filter(Script.is_deleted == False)
    query = restrict_script_query(query, current_user)
    scripts = query.order_by(Script.updated_at.desc()).all()
    return [_script_brief_from_orm(script, db, current_user) for script in scripts]


@router.get("/authorized-ids", response_model=List[int])
def list_authorized_script_ids(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Script.id).filter(
        Script.is_deleted == False,
        Script.status == "active",
    )
    query = restrict_script_query(query, current_user)
    return [int(row[0]) for row in query.order_by(Script.id).all()]


@router.post("/{script_id}/install")
def install_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    script = get_accessible_script_or_404(
        db, current_user, script_id, require_active=True,
    )

    existing = db.query(UserScript).filter(
        UserScript.user_id == current_user.id, UserScript.script_id == script_id
    ).first()
    if existing:
        return {"message": "已安装"}

    db.add(UserScript(user_id=current_user.id, script_id=script_id))
    db.commit()
    write_audit(current_user.id, current_user.username, "install_script",
                target_type="script", target_id=script_id, detail=script.name)
    return {"message": "已安装"}


@router.post("/{script_id}/uninstall")
def uninstall_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(UserScript).filter(
        UserScript.user_id == current_user.id, UserScript.script_id == script_id
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="尚未安装该脚本")
    db.delete(existing)
    db.commit()
    write_audit(current_user.id, current_user.username, "uninstall_script",
                target_type="script", target_id=script_id)
    return {"message": "已卸载"}


@router.post("/upload", response_model=ScriptDetail)
def upload_script(
    file: UploadFile = File(...),
    changelog: str = Form(""),
    group_ids: Optional[str] = Form(None),
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")

    safe_name = _safe_upload_name(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".py", ".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .py 和 .zip 文件")

    script_type = "zip" if ext == ".zip" else "py"

    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, "upload" + ext)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        config = _validated_upload(tmp_path)
        groups = _upload_groups(db, current_user, group_ids)

        script = Script(
            name=config.get("name", safe_name),
            description=config.get("description", ""),
            category=config.get("category", ""),
            type=script_type,
            latest_version=1,
            config_json=json.dumps(config, ensure_ascii=False),
            status="active",
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(script)
        db.flush()
        script.groups = groups

        save_script_file(script.id, 1, tmp_path, script_type)

        version = ScriptVersion(
            script_id=script.id,
            version=1,
            changelog=changelog or "初始版本",
            file_path=os.path.join("storage/scripts", str(script.id), "1"),
            config_json=json.dumps(config, ensure_ascii=False),
            created_by=current_user.id,
        )
        db.add(version)
        db.commit()
        db.refresh(script)
        write_audit(current_user.id, current_user.username, "upload_script",
                    target_type="script", target_id=script.id, detail=script.name)
        return _script_detail_from_orm(script, db, current_user)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/{script_id}/upload-version", response_model=ScriptDetail)
def upload_version(
    script_id: int,
    file: UploadFile = File(...),
    changelog: str = Form(""),
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    script = get_manageable_script_or_404(db, current_user, script_id)

    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")

    safe_name = _safe_upload_name(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".py", ".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .py 和 .zip 文件")

    script_type = "zip" if ext == ".zip" else "py"
    new_version = script.latest_version + 1

    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, "upload" + ext)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        config = _validated_upload(tmp_path)

        save_script_file(script.id, new_version, tmp_path, script_type)

        version = ScriptVersion(
            script_id=script.id,
            version=new_version,
            changelog=changelog or f"版本 {new_version}",
            file_path=os.path.join("storage/scripts", str(script.id), str(new_version)),
            config_json=json.dumps(config, ensure_ascii=False),
            created_by=current_user.id,
        )
        db.add(version)

        script.latest_version = new_version
        script.config_json = json.dumps(config, ensure_ascii=False)
        script.name = config.get("name", script.name)
        script.description = config.get("description", script.description)
        script.category = config.get("category", script.category)
        script.updated_by = current_user.id
        db.commit()
        db.refresh(script)
        write_audit(current_user.id, current_user.username, "upload_version",
                    target_type="script", target_id=script.id,
                    detail="v{} {}".format(new_version, script.name))
        return _script_detail_from_orm(script, db, current_user)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.put("/{script_id}/groups", response_model=ScriptDetail)
def update_script_groups(
    script_id: int,
    req: ScriptGroupUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    script = get_manageable_script_or_404(db, current_user, script_id)
    script.groups = assignable_groups(
        db, current_user, req.group_ids, allow_empty=True,
    )
    script.updated_by = current_user.id
    db.commit()
    db.refresh(script)
    write_audit(
        current_user.id, current_user.username, "update_script_groups",
        target_type="script", target_id=script.id,
        detail="group_ids={}".format(sorted(group.id for group in script.groups)),
    )
    return _script_detail_from_orm(script, db, current_user)


@router.get("/{script_id}", response_model=ScriptDetail)
def get_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    script = get_accessible_script_or_404(db, current_user, script_id)
    return _script_detail_from_orm(script, db, current_user)


@router.get("/{script_id}/download")
def download_script(
    script_id: int,
    version: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download script files as a ZIP archive."""
    from fastapi.responses import FileResponse
    from app.services.script_storage import get_script_file_path

    script = get_accessible_script_or_404(db, current_user, script_id)

    ver = version or script.latest_version
    script_dir = get_script_file_path(script_id, ver)
    if not script_dir:
        raise HTTPException(status_code=404, detail="服务器上找不到脚本文件")

    # Zip the script directory
    import tempfile
    import shutil
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_name = tmp.name
    tmp.close()

    shutil.make_archive(tmp_name.replace(".zip", ""), "zip", script_dir)

    filename = "{}-v{}.zip".format(script.name.replace(" ", "_"), ver)
    return FileResponse(tmp_name, filename=filename, media_type="application/zip")


@router.get("/{script_id}/versions", response_model=List[ScriptVersionBrief])
def list_versions(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_script_or_404(db, current_user, script_id)
    return db.query(ScriptVersion).filter(
        ScriptVersion.script_id == script_id
    ).order_by(ScriptVersion.version.desc()).all()


@router.post("/{script_id}/disable")
def disable_script(
    script_id: int,
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    script = get_manageable_script_or_404(db, current_user, script_id)
    script.status = "disabled"
    script.updated_by = current_user.id
    db.commit()
    write_audit(current_user.id, current_user.username, "disable_script",
                target_type="script", target_id=script.id, detail=script.name)
    return {"message": "脚本已禁用"}


@router.post("/{script_id}/enable")
def enable_script(
    script_id: int,
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    script = get_manageable_script_or_404(db, current_user, script_id)
    script.status = "active"
    script.updated_by = current_user.id
    db.commit()
    write_audit(current_user.id, current_user.username, "enable_script",
                target_type="script", target_id=script.id, detail=script.name)
    return {"message": "脚本已启用"}
