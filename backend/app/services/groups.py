"""Group lifecycle and membership helpers."""

from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Group, User


DEFAULT_GROUP_NAME = "默认分组"


def get_default_group(db: Session) -> Optional[Group]:
    return db.query(Group).filter(
        Group.is_default == True,
        Group.status == "active",
        Group.is_deleted == False,
    ).order_by(Group.id).first()


def get_or_create_default_group(db: Session, actor_id: Optional[int] = None) -> Group:
    group = get_default_group(db)
    if group:
        return group
    group = db.query(Group).filter(
        Group.name == DEFAULT_GROUP_NAME,
        Group.is_deleted == False,
    ).first()
    if group:
        group.status = "active"
        group.is_default = True
        group.updated_by = actor_id
    else:
        group = Group(
            name=DEFAULT_GROUP_NAME,
            description="默认市场分组",
            status="active",
            is_default=True,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(group)
    db.flush()
    return group


def active_groups_by_ids(db: Session, group_ids: Iterable[int]) -> list[Group]:
    ids = list(dict.fromkeys(int(item) for item in group_ids))
    if not ids:
        return []
    groups = db.query(Group).filter(
        Group.id.in_(ids),
        Group.status == "active",
        Group.is_deleted == False,
    ).order_by(Group.id).all()
    if {group.id for group in groups} != set(ids):
        raise HTTPException(status_code=400, detail="分组不存在或已停用")
    return groups


def set_user_groups(
    db: Session,
    user: User,
    group_ids: Optional[Iterable[int]],
    actor_id: Optional[int] = None,
) -> None:
    if group_ids is None:
        user.groups = [get_or_create_default_group(db, actor_id)]
    else:
        user.groups = active_groups_by_ids(db, group_ids)


def set_default_group(db: Session, group: Group, actor_id: Optional[int]) -> None:
    for current in db.query(Group).filter(
        Group.is_default == True,
        Group.is_deleted == False,
        Group.id != group.id,
    ).all():
        current.is_default = False
        current.updated_by = actor_id
    try:
        db.flush()
        group.is_default = True
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="默认分组已被其他操作更新，请重试") from exc
