from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Group, Script, User
from app.schemas import GroupBrief, GroupCreate, GroupDetail, GroupUpdate
from app.services.audit import write_audit
from app.services.groups import set_default_group


router = APIRouter(prefix="/api/groups", tags=["groups"])


def _counts(db: Session, group: Group) -> tuple[int, int]:
    user_count = db.query(User).filter(
        User.is_deleted == False,
        User.groups.any(Group.id == group.id),
    ).count()
    script_count = db.query(Script).filter(
        Script.is_deleted == False,
        Script.groups.any(Group.id == group.id),
    ).count()
    return user_count, script_count


def _detail(db: Session, group: Group) -> GroupDetail:
    user_count, script_count = _counts(db, group)
    item = GroupDetail.model_validate(group)
    item.user_count = user_count
    item.script_count = script_count
    return item


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=422, detail="分组名称不能为空")
    return name


@router.get("/available", response_model=List[GroupBrief])
def list_available_groups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Group).filter(
        Group.status == "active",
        Group.is_deleted == False,
    )
    if current_user.role != "admin":
        query = query.filter(Group.users.any(User.id == current_user.id))
    return query.order_by(Group.is_default.desc(), Group.name).all()


@router.get("", response_model=List[GroupDetail])
def list_groups(
    search: str = Query(default="", max_length=100),
    status: Optional[str] = None,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    query = db.query(Group).filter(Group.is_deleted == False)
    keyword = search.strip()
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(Group.name.ilike(pattern), Group.description.ilike(pattern)))
    if status:
        query = query.filter(Group.status == status)
    groups = query.order_by(Group.is_default.desc(), Group.id).all()
    return [_detail(db, group) for group in groups]


@router.post("", response_model=GroupDetail)
def create_group(
    req: GroupCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    name = _clean_name(req.name)
    if db.query(Group).filter(Group.name == name).first():
        raise HTTPException(status_code=409, detail="分组名称已存在")
    if req.is_default and req.status != "active":
        raise HTTPException(status_code=400, detail="默认分组必须处于启用状态")
    group = Group(
        name=name,
        description=(req.description or "").strip() or None,
        status=req.status,
        is_default=False,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(group)
    db.flush()
    if req.is_default:
        set_default_group(db, group, current_user.id)
    db.commit()
    db.refresh(group)
    write_audit(
        current_user.id, current_user.username, "create_group",
        target_type="group", target_id=group.id, detail=group.name,
    )
    return _detail(db, group)


@router.put("/{group_id}", response_model=GroupDetail)
def update_group(
    group_id: int,
    req: GroupUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id, Group.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="分组不存在")
    if req.name is not None:
        name = _clean_name(req.name)
        duplicate = db.query(Group).filter(Group.name == name, Group.id != group.id).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="分组名称已存在")
        group.name = name
    if req.description is not None:
        group.description = req.description.strip() or None
    if req.status is not None:
        if group.is_default and req.status != "active":
            raise HTTPException(status_code=400, detail="默认分组不能停用，请先设置其他默认分组")
        group.status = req.status
    if req.is_default is False and group.is_default:
        raise HTTPException(status_code=400, detail="不能直接取消默认分组，请将其他分组设为默认")
    if req.is_default is True:
        if group.status != "active":
            raise HTTPException(status_code=400, detail="默认分组必须处于启用状态")
        set_default_group(db, group, current_user.id)
    group.updated_by = current_user.id
    db.commit()
    db.refresh(group)
    write_audit(
        current_user.id, current_user.username, "update_group",
        target_type="group", target_id=group.id, detail=group.name,
    )
    return _detail(db, group)


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id, Group.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="分组不存在")
    if group.is_default:
        raise HTTPException(status_code=400, detail="默认分组不能删除，请先设置其他默认分组")
    user_count, script_count = _counts(db, group)
    if user_count or script_count:
        raise HTTPException(
            status_code=409,
            detail=f"分组仍关联 {user_count} 个用户和 {script_count} 个脚本，请先迁移关联",
        )
    group.is_deleted = True
    group.status = "disabled"
    group.updated_by = current_user.id
    db.commit()
    write_audit(
        current_user.id, current_user.username, "delete_group",
        target_type="group", target_id=group.id, detail=group.name,
    )
    return {"message": "分组已删除"}
