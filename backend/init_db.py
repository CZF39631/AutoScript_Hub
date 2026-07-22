"""Create database tables and seed admin user."""
import json
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models import User
from app.database import engine, SessionLocal
from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, DATABASE_URL, SCRIPTS_DIR, LOGS_DIR, PROJECT_ROOT
from app.auth import hash_password
from app.migrations import upgrade_database

logger = logging.getLogger(__name__)


def _load_admin_config():
    cfg_path = os.path.join(PROJECT_ROOT, "config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load admin config: %s", e)
    return {}


def init():
    # Derive from the active engine so tests and alternate engine bindings migrate
    # the same database that SessionLocal will use.
    upgrade_database(str(engine.url))

    # Read admin credentials from config.json
    admin_user = ADMIN_USERNAME
    admin_pass = ADMIN_PASSWORD

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == admin_user).first()
        if not admin:
            admin = User(
                username=admin_user,
                password_hash=hash_password(admin_pass),
                display_name="管理员",
                role="admin",
                status="active",
            )
            db.add(admin)
            db.commit()
            print("Created admin user: {} / ***".format(admin_user))
        else:
            print("Admin user already exists")
    finally:
        db.close()

    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    print("Database initialized.")


if __name__ == "__main__":
    init()
