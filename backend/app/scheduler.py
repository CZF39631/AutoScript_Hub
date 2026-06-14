"""Background scheduler for periodic server-side tasks.

Runs in a daemon thread started from FastAPI startup event. Two jobs:
  1. Heartbeat scan (design §5.1): every 30s, mark agents with >90s stale heartbeat
     as offline, and fail their running runs (server-side watchdog).
  2. Log cleanup (design §5.12): daily at 03:00, archive logs older than 30 days,
     delete archives older than 90 days.
"""
import logging
import os
import threading
import time
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import LOGS_DIR, LOG_ARCHIVE_DIR, LOG_RETENTION_DAYS, LOG_ARCHIVE_RETENTION_DAYS, LOG_CLEANUP_HOUR
from app.database import SessionLocal
from app.models import Agent, Run

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SEC = 30
HEARTBEAT_TIMEOUT_SEC = 90

# Module-level state for daily log cleanup
_last_cleanup_date: Optional[str] = None


def start_scheduler() -> None:
    """Start the background scheduler thread. Idempotent."""
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="autoscript-scheduler")
    t.start()
    logger.info("Background scheduler started (scan every %ss)", SCAN_INTERVAL_SEC)


def _scheduler_loop() -> None:
    # Give the app a moment to finish startup before first scan
    time.sleep(5)
    while True:
        try:
            _heartbeat_scan()
            _maybe_log_cleanup()
        except Exception:
            logger.exception("Scheduler iteration failed")
        time.sleep(SCAN_INTERVAL_SEC)


def _heartbeat_scan() -> None:
    """Mark agents with stale heartbeat offline + fail their running runs (§5.1)."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TIMEOUT_SEC)
    db = SessionLocal()
    try:
        stale_agents = db.query(Agent).filter(
            Agent.status == "online",
            Agent.is_deleted == False,
            Agent.last_heartbeat < cutoff,
        ).all()

        if not stale_agents:
            return

        stale_agent_ids = [a.id for a in stale_agents]

        # Mark agents offline
        for agent in stale_agents:
            agent.status = "offline"

        # Fail their running runs
        stuck_runs = db.query(Run).filter(
            Run.agent_id.in_(stale_agent_ids),
            Run.status == "running",
            Run.is_deleted == False,
        ).all()
        now = datetime.now(timezone.utc)
        for run in stuck_runs:
            run.status = "failed"
            run.error_msg = "Agent heartbeat timeout (server-side watchdog)"
            run.finished_at = now
            if run.started_at:
                run.duration_sec = int((now - run.started_at).total_seconds())

        db.commit()
        if stale_agents or stuck_runs:
            logger.warning(
                "Heartbeat scan: %d agents → offline, %d runs → failed",
                len(stale_agents), len(stuck_runs),
            )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _maybe_log_cleanup() -> None:
    """Run log cleanup once per day after LOG_CLEANUP_HOUR."""
    global _last_cleanup_date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if today == _last_cleanup_date:
        return
    if now.hour < LOG_CLEANUP_HOUR:
        return

    try:
        _log_cleanup(now)
        _last_cleanup_date = today
        logger.info("Daily log cleanup completed for %s", today)
    except Exception:
        logger.exception("Log cleanup failed")


def _log_cleanup(now: datetime) -> None:
    """Archive logs older than LOG_RETENTION_DAYS, delete archives > LOG_ARCHIVE_RETENTION_DAYS."""
    os.makedirs(LOG_ARCHIVE_DIR, exist_ok=True)

    # 1) Archive old logs (runs finished > LOG_RETENTION_DAYS ago, not running)
    cutoff_finished = now - timedelta(days=LOG_RETENTION_DAYS)
    db = SessionLocal()
    try:
        old_runs = db.query(Run).filter(
            Run.status != "running",
            Run.is_deleted == False,
            Run.finished_at < cutoff_finished,
        ).all()
        for run in old_runs:
            if run.log_path:
                _archive_log(run.log_path)
            else:
                # Fallback: storage/logs/{id}.log
                fallback = os.path.join(LOGS_DIR, "{}.log".format(run.id))
                if os.path.isfile(fallback):
                    _archive_log(fallback)
    finally:
        db.close()

    # 2) Delete archives older than LOG_ARCHIVE_RETENTION_DAYS
    archive_cutoff = now - timedelta(days=LOG_ARCHIVE_RETENTION_DAYS)
    if os.path.isdir(LOG_ARCHIVE_DIR):
        for fname in os.listdir(LOG_ARCHIVE_DIR):
            fpath = os.path.join(LOG_ARCHIVE_DIR, fname)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < archive_cutoff:
                    os.remove(fpath)
                    logger.info("Deleted old archive: %s", fname)
            except OSError:
                continue


def _archive_log(log_path: str) -> None:
    """Move a log file into LOG_ARCHIVE_DIR as a compressed zip. Safe if file missing."""
    if not log_path:
        return
    # log_path may be absolute or relative to PROJECT_ROOT
    full_path = log_path if os.path.isabs(log_path) else os.path.join(LOGS_DIR, os.path.basename(log_path))
    # Try the path as-is first, then under LOGS_DIR
    if not os.path.isfile(full_path):
        full_path = os.path.join(LOGS_DIR, os.path.basename(log_path))
    if not os.path.isfile(full_path):
        return

    base = os.path.basename(full_path)
    archive_zip = os.path.join(LOG_ARCHIVE_DIR, base + ".zip")
    try:
        with zipfile.ZipFile(archive_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(full_path, base)
        os.remove(full_path)
        logger.info("Archived log: %s → %s", base, archive_zip)
    except OSError as e:
        logger.warning("Failed to archive log %s: %s", base, e)
