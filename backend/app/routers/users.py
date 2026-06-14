from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserUpdate, UserDetail
from app.auth import get_current_user, require_role, hash_password
from app.services.audit import write_audit

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[UserDetail])
def list_users(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return db.query(User).filter(User.is_deleted == False).all()


@router.post("", response_model=UserDetail)
def create_user(
    req: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    exists = db.query(User).filter(User.username == req.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
        role=req.role,
        status="active",
        created_by=current_user.id,
    )
    db.add(user)
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
    changes = []
    if req.display_name is not None:
        user.display_name = req.display_name
        changes.append("display_name")
    if req.role is not None:
        user.role = req.role
        changes.append("role={}".format(req.role))
    if req.status is not None:
        user.status = req.status
        changes.append("status={}".format(req.status))
    user.updated_by = current_user.id
    db.commit()
    db.refresh(user)
    write_audit(current_user.id, current_user.username, "update_user",
                target_type="user", target_id=user_id,
                detail="{} changed: {}".format(user.username, ", ".join(changes)))
    return user
