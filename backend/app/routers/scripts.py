import json
import os
import shutil
import tempfile
import zipfile
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Script, ScriptVersion, UserScript
from app.schemas import ScriptBrief, ScriptDetail, ScriptVersionBrief
from app.auth import get_current_user, require_role
from app.services.script_parser import parse_script_config
from app.services.script_storage import save_script_file
from app.services.audit import write_audit

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


def _is_admin(current_user):
    return current_user.role == "admin"


def _can_manage_scripts(current_user):
    """Admin and developer can both see all scripts (design §1.3: developer uploads/manages scripts)."""
    return current_user.role in ("admin", "developer")


@router.get("", response_model=List[ScriptBrief])
def list_scripts(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Script).filter(Script.is_deleted == False, Script.status == "active")
    if category:
        q = q.filter(Script.category == category)

    # Admin and developer see all scripts (design §1.3: developer manages scripts)
    if _can_manage_scripts(current_user):
        return q.order_by(Script.updated_at.desc()).all()

    # Non-admin: only installed scripts
    installed_ids = [us.script_id for us in
                     db.query(UserScript).filter(UserScript.user_id == current_user.id).all()]
    if not installed_ids:
        return []
    q = q.filter(Script.id.in_(installed_ids))
    return q.order_by(Script.updated_at.desc()).all()


@router.get("/marketplace", response_model=List[ScriptBrief])
def list_marketplace(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Script).filter(Script.is_deleted == False, Script.status == "active")
    if category:
        q = q.filter(Script.category == category)
    scripts = q.order_by(Script.updated_at.desc()).all()

    installed_ids = set()
    if not _is_admin(current_user):
        installed_ids = {us.script_id for us in
                        db.query(UserScript).filter(UserScript.user_id == current_user.id).all()}

    result = []
    for s in scripts:
        item = ScriptBrief.from_orm(s)
        if _is_admin(current_user):
            item.installed = True
        else:
            item.installed = s.id in installed_ids
        result.append(item)
    return result


@router.post("/{script_id}/install")
def install_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_admin(current_user):
        return {"message": "管理员拥有所有脚本权限"}

    script = db.query(Script).filter(Script.id == script_id, Script.is_deleted == False, Script.status == "active").first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")

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
    if _is_admin(current_user):
        return {"message": "管理员无法卸载"}

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
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".py", ".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .py 和 .zip 文件")

    script_type = "zip" if ext == ".zip" else "py"

    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        parse_path = tmp_path
        if script_type == "zip":
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(tmp_dir)
            for root, dirs, files in os.walk(tmp_dir):
                if "main.py" in files:
                    parse_path = os.path.join(root, "main.py")
                    break

        config = parse_script_config(parse_path)
        if not config:
            raise HTTPException(status_code=400, detail="脚本必须包含 config() 函数")

        script = Script(
            name=config.get("name", file.filename),
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
        return script

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
    script = db.query(Script).filter(Script.id == script_id, Script.is_deleted == False).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")

    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".py", ".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .py 和 .zip 文件")

    script_type = "zip" if ext == ".zip" else "py"
    new_version = script.latest_version + 1

    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        parse_path = tmp_path
        if script_type == "zip":
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(tmp_dir)
            for root, dirs, files in os.walk(tmp_dir):
                if "main.py" in files:
                    parse_path = os.path.join(root, "main.py")
                    break

        config = parse_script_config(parse_path)
        if not config:
            raise HTTPException(status_code=400, detail="脚本必须包含 config() 函数")

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
        return script

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/{script_id}", response_model=ScriptDetail)
def get_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    script = db.query(Script).filter(Script.id == script_id, Script.is_deleted == False).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return script


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

    script = db.query(Script).filter(Script.id == script_id, Script.is_deleted == False).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")

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
    return db.query(ScriptVersion).filter(
        ScriptVersion.script_id == script_id
    ).order_by(ScriptVersion.version.desc()).all()


@router.post("/{script_id}/disable")
def disable_script(
    script_id: int,
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    script = db.query(Script).filter(Script.id == script_id, Script.is_deleted == False).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
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
    script = db.query(Script).filter(Script.id == script_id, Script.is_deleted == False).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
    script.status = "active"
    script.updated_by = current_user.id
    db.commit()
    write_audit(current_user.id, current_user.username, "enable_script",
                target_type="script", target_id=script.id, detail=script.name)
    return {"message": "脚本已启用"}
