"""Serialize script deletion and run creation within the caller's transaction."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Script


def lock_script_for_lifecycle(db: Session, script_id: int) -> None:
    # A real UPDATE also acquires SQLite's write lock (FOR UPDATE does not).
    # Explicit self-assignment suppresses the updated_at onupdate default.
    # Do not commit here: the caller must retain the lock through its mutation.
    db.execute(
        update(Script).where(Script.id == script_id).values(updated_at=Script.updated_at),
        execution_options={"synchronize_session": False},
    )
    # A prior permission check may have populated the identity map. Force the
    # post-lock authorization/read to see current status, config and revision.
    db.expire_all()
