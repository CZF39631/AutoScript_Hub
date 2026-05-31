from datetime import datetime
from app.database import SessionLocal
from app.models import AuditLog


def write_audit(user_id, username, action, target_type=None, target_id=None, detail=None, ip_address=None):
    """Write an audit log entry. Safe to call from any context — creates its own session."""
    db = SessionLocal()
    try:
        entry = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip_address=ip_address,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
