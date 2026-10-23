import logging
from datetime import datetime, timezone
from app.database import SessionLocal
from app.models import AuditLog

logger = logging.getLogger(__name__)


def write_audit(
    user_id, username, action, target_type=None, target_id=None, detail=None,
    ip_address=None, db=None,
):
    """Write an audit entry, optionally in the request's configured DB session."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        entry = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc),
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Failed to write audit log: action=%s user=%s", action, username)
        if not owns_session:
            raise
    finally:
        if owns_session:
            db.close()
