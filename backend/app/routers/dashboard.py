from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.database import get_db
from app.models import User, Script, Run, AuditLog, UserScript, Group
from app.auth import get_current_user, require_role
from app.services.script_access import (
    accessible_script_ids,
    accessible_user_ids,
    active_group_ids_for_user,
    restrict_script_query,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    if current_user.role == "admin":
        own_run_filter = True
    elif current_user.role == "operator":
        own_run_filter = Run.user_id == current_user.id
    else:
        own_run_filter = or_(
            Run.user_id == current_user.id,
            (
                Run.script_id.in_(accessible_script_ids(current_user))
                & Run.user_id.in_(accessible_user_ids(current_user))
            ),
        )

    # Statistics use the same role and group boundary as run history.
    total_runs = db.query(func.count(Run.id)).filter(Run.is_deleted == False, own_run_filter).scalar()
    if current_user.role == "operator":
        total_scripts = db.query(func.count(UserScript.id)).filter(
            UserScript.user_id == current_user.id
        ).scalar()
        total_users = 1
    elif current_user.role == "developer":
        total_scripts = restrict_script_query(
            db.query(Script).filter(Script.is_deleted == False, Script.status == "active"),
            current_user,
        ).count()
        group_ids = active_group_ids_for_user(db, current_user)
        total_users = db.query(User).filter(
            User.is_deleted == False,
            User.groups.any(Group.id.in_(group_ids)) if group_ids else User.id == current_user.id,
        ).count()
    else:
        total_scripts = db.query(func.count(Script.id)).filter(
            Script.is_deleted == False, Script.status == "active"
        ).scalar()
        total_users = db.query(func.count(User.id)).filter(User.is_deleted == False).scalar()

    # Today
    today_runs = db.query(func.count(Run.id)).filter(
        Run.is_deleted == False, own_run_filter, Run.created_at >= today_start
    ).scalar()
    today_success = db.query(func.count(Run.id)).filter(
        Run.is_deleted == False, own_run_filter, Run.created_at >= today_start, Run.status == "success"
    ).scalar()
    today_failed = db.query(func.count(Run.id)).filter(
        Run.is_deleted == False, own_run_filter, Run.created_at >= today_start, Run.status == "failed"
    ).scalar()

    # This week
    week_runs = db.query(func.count(Run.id)).filter(
        Run.is_deleted == False, own_run_filter, Run.created_at >= week_start
    ).scalar()
    week_success = db.query(func.count(Run.id)).filter(
        Run.is_deleted == False, own_run_filter, Run.created_at >= week_start, Run.status == "success"
    ).scalar()

    # Recent failed runs
    recent_failed = db.query(Run).filter(
        Run.is_deleted == False, own_run_filter, Run.status == "failed"
    ).order_by(Run.created_at.desc()).limit(5).all()

    failed_list = []
    for r in recent_failed:
        script = db.query(Script).filter(Script.id == r.script_id).first()
        user = db.query(User).filter(User.id == r.user_id).first()
        failed_list.append({
            "run_id": r.id,
            "script_name": script.name if script else "Unknown",
            "username": user.display_name if user else "Unknown",
            "error_msg": (r.error_msg or "")[:100],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    # Script execution ranking (top 5)
    script_stats = db.query(
        Run.script_id, func.count(Run.id).label("cnt")
    ).filter(
        Run.is_deleted == False, own_run_filter, Run.created_at >= week_start
    ).group_by(Run.script_id).order_by(func.count(Run.id).desc()).limit(5).all()

    ranking = []
    for sid, cnt in script_stats:
        script = db.query(Script).filter(Script.id == sid).first()
        ranking.append({"script_name": script.name if script else "Unknown", "count": cnt})

    # Online users (logged in within 30 min)
    online_threshold = now - timedelta(minutes=30)
    if current_user.role == "operator":
        last_login = current_user.last_login_at
        if last_login is not None and last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=timezone.utc)
        online_users = int(
            current_user.status == "active"
            and last_login is not None
            and last_login >= online_threshold
        )
    elif current_user.role == "developer":
        group_ids = active_group_ids_for_user(db, current_user)
        online_users = db.query(User).filter(
            User.is_deleted == False,
            User.status == "active",
            User.last_login_at >= online_threshold,
            User.groups.any(Group.id.in_(group_ids)) if group_ids else User.id == current_user.id,
        ).count()
    else:
        online_users = db.query(func.count(User.id)).filter(
            User.is_deleted == False, User.status == "active",
            User.last_login_at >= online_threshold
        ).scalar()

    return {
        "total_runs": total_runs,
        "total_scripts": total_scripts,
        "total_users": total_users,
        "today_runs": today_runs,
        "today_success": today_success,
        "today_failed": today_failed,
        "today_success_rate": round(today_success / today_runs * 100, 1) if today_runs > 0 else 0,
        "week_runs": week_runs,
        "week_success": week_success,
        "week_success_rate": round(week_success / week_runs * 100, 1) if week_runs > 0 else 0,
        "online_users": online_users,
        "recent_failed": failed_list,
        "script_ranking": ranking,
    }
