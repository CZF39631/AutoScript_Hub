from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Group, User
from app.schemas import UserCreate, UserUpdate, UserDetail
from app.auth import require_role, hash_password
from app.services.audit import write_audit
from app.services.groups import set_user_groups

router = APIRouter(prefix="/api/users", tags=["users"])


def _active_admin_count(db: Session) -> int:
    return db.query(User).filter(
        User.role == "admin",
        User.status == "active",
        User.is_deleted == False,
    ).count()


def _protect_admin_transition(db: Session, user: User, role=None, status=None) -> None:
    next_role = role if role is not None else user.role
    next_status = status if status is not None else user.status
    removes_active_admin = (
        user.role == "admin"
        and user.status == "active"
        and (next_role != "admin" or next_status != "active")
    )
    if removes_active_admin and _active_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="不能移除或禁用最后一个有效管理员")


@router.get("", response_model=List[UserDetail])
def list_users(
    search: str = Query(default="", max_length=100),
    group_id: Optional[int] = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    query = db.query(User).filter(User.is_deleted == False)
    keyword = search.strip()
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(User.username.ilike(pattern), User.display_name.ilike(pattern)))
    if group_id is not None:
        query = query.filter(User.groups.any(Group.id == group_id))
    return query.order_by(User.id.desc()).all()


@router.post("", response_model=UserDetail)
def create_user(
    req: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    username = req.username.strip()
    display_name = req.display_name.strip()
    if not username or not display_name:
        raise HTTPException(status_code=422, detail="用户名和显示名不能为空")
    exists = db.query(User).filter(User.username == username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(req.password),
        display_name=display_name,
        role=req.role,
        status="active",
        created_by=current_user.id,
    )
    db.add(user)
    db.flush()
    set_user_groups(db, user, req.group_ids, current_user.id)
    db.commit()
    db.refresh(user)
    write_audit(current_user.id, current_user.username, "create_user",
                target_type="user", target_id=user.id, detail=user.username)
    return user


@router.put("/{user_id}", response_model=UserDetail)
def update_user(
    user_id: int,
    req: UserUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        if req.role is not None and req.role != "admin":
            raise HTTPException(status_code=400, detail="不能降低自己的管理员权限")
        if req.status is not None and req.status != "active":
            raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    _protect_admin_transition(db, user, req.role, req.status)

    changes = []
    if req.display_name is not None:
        display_name = req.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=422, detail="显示名不能为空")
        if display_name != user.display_name:
            changes.append(f"display_name={user.display_name} -> {display_name}")
            user.display_name = display_name
    if req.role is not None and req.role != user.role:
        changes.append(f"role={user.role} -> {req.role}")
        user.role = req.role
    if req.status is not None and req.status != user.status:
        changes.append(f"status={user.status} -> {req.status}")
        user.status = req.status
    if req.group_ids is not None:
        previous_ids = {group.id for group in user.groups}
        set_user_groups(db, user, req.group_ids, current_user.id)
        next_ids = {group.id for group in user.groups}
        if previous_ids != next_ids:
            changes.append(f"groups={sorted(previous_ids)} -> {sorted(next_ids)}")
    user.updated_by = current_user.id
    db.commit()
    db.refresh(user)
    write_audit(current_user.id, current_user.username, "update_user",
                target_type="user", target_id=user_id,
                detail="{} changed: {}".format(user.username, ", ".join(changes) or "no changes"))
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    _protect_admin_transition(db, user, role="operator", status="disabled")

    deleted_username = user.username
    deleted_role = user.role
    user.is_deleted = True
    user.status = "disabled"
    user.updated_by = current_user.id
    db.commit()
    write_audit(current_user.id, current_user.username, "delete_user",
                target_type="user", target_id=user_id,
                detail=f"{deleted_username} deleted (role={deleted_role})")
    return {"message": "用户已删除"}
