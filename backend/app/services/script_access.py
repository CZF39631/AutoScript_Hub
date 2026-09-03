"""Central group-based authorization for scripts and related resources."""

from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Query, Session

from app.models import Group, Script, User, script_groups, user_groups
from app.services.groups import active_groups_by_ids


def active_group_ids_for_user(db: Session, user: User) -> set[int]:
    rows = db.query(user_groups.c.group_id).join(
        Group, Group.id == user_groups.c.group_id
    ).filter(
        user_groups.c.user_id == user.id,
        Group.status == "active",
        Group.is_deleted == False,
    ).all()
    return {int(row[0]) for row in rows}


def accessible_user_ids(user: User):
    """Return users sharing at least one active group with the actor."""
    actor_groups = user_groups.alias("actor_groups")
    target_groups = user_groups.alias("target_groups")
    return select(target_groups.c.user_id).select_from(
        actor_groups.join(
            target_groups,
            actor_groups.c.group_id == target_groups.c.group_id,
        ).join(Group, Group.id == actor_groups.c.group_id)
    ).where(
        actor_groups.c.user_id == user.id,
        Group.status == "active",
        Group.is_deleted == False,
    )


def accessible_script_ids(user: User):
    """Return a SQL subquery of scripts sharing an active group with user."""
    return select(script_groups.c.script_id).select_from(
        script_groups.join(
            user_groups,
            script_groups.c.group_id == user_groups.c.group_id,
        ).join(Group, Group.id == script_groups.c.group_id)
    ).where(
        user_groups.c.user_id == user.id,
        Group.status == "active",
        Group.is_deleted == False,
    )


def restrict_script_query(query: Query, user: User) -> Query:
    if user.role == "admin":
        return query
    return query.filter(Script.id.in_(accessible_script_ids(user)))


def can_access_script(db: Session, user: User, script: Script) -> bool:
    if user.role == "admin":
        return True
    return db.query(script_groups.c.script_id).select_from(
        script_groups.join(
            user_groups,
            script_groups.c.group_id == user_groups.c.group_id,
        ).join(Group, Group.id == script_groups.c.group_id)
    ).filter(
        script_groups.c.script_id == script.id,
        user_groups.c.user_id == user.id,
        Group.status == "active",
        Group.is_deleted == False,
    ).first() is not None


def can_manage_script(db: Session, user: User, script: Script) -> bool:
    if user.role == "admin":
        return True
    return user.role == "developer" and can_access_script(db, user, script)


def get_accessible_script_or_404(
    db: Session,
    user: User,
    script_id: int,
    *,
    require_active: bool = False,
) -> Script:
    query = db.query(Script).filter(
        Script.id == script_id,
        Script.is_deleted == False,
    )
    if require_active:
        query = query.filter(Script.status == "active")
    script = restrict_script_query(query, user).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在或无访问权限")
    return script


def get_manageable_script_or_404(db: Session, user: User, script_id: int) -> Script:
    script = db.query(Script).filter(
        Script.id == script_id,
        Script.is_deleted == False,
    ).first()
    if not script or not can_manage_script(db, user, script):
        raise HTTPException(status_code=404, detail="脚本不存在或无管理权限")
    return script


def assignable_groups(db: Session, user: User, group_ids: Iterable[int], *, allow_empty: bool) -> list[Group]:
    ids = list(dict.fromkeys(int(item) for item in group_ids))
    if not ids:
        if allow_empty and user.role == "admin":
            return []
        raise HTTPException(status_code=400, detail="至少选择一个可见分组")
    groups = active_groups_by_ids(db, ids)
    if user.role != "admin":
        own_ids = active_group_ids_for_user(db, user)
        if not set(ids).issubset(own_ids):
            raise HTTPException(status_code=403, detail="不能将脚本分配到自己所属范围之外")
    return groups
