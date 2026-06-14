"""Create database tables and seed admin user."""
import json
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models import Base, User
from app.database import engine, SessionLocal
from passlib.context import CryptContext
from app.config import SCRIPTS_DIR, LOGS_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _load_admin_config():
    cfg_path = os.path.join(PROJECT_ROOT, "config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load admin config: %s", e)
    return {}


def _migrate(conn):
    """Add missing columns to existing tables."""
    migrations = [
        ("runs", "environment_id", "INTEGER REFERENCES environments(id)"),
        ("environments", "python_version", "VARCHAR(20)"),
        ("environments", "venv_path", "VARCHAR(500)"),
        ("environments", "venv_status", "VARCHAR(20) DEFAULT 'none'"),
        ("environments", "python_executable", "VARCHAR(500)"),
        # design §4.4 / §4.5: agents table + run.agent_id (machine identity tracking)
        ("runs", "agent_id", "INTEGER REFERENCES agents(id)"),
        # design §4.6: issues missing fields
        ("issues", "script_version", "INTEGER"),
        ("issues", "log_snapshot", "TEXT"),
        ("issues", "resolved_version", "INTEGER"),
    ]
    for table, column, definition in migrations:
        try:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                print(f"  Added column {table}.{column}")
        except Exception as e:
            print(f"  Migration {table}.{column} skipped: {e}")

    # Create user_settings table
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
                settings_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
    except Exception as e:
        logger.debug("user_settings table already exists or creation skipped: %s", e)


def init():
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        _migrate(conn)

    # Read admin credentials from config.json
    admin_cfg = _load_admin_config()
    admin_user = admin_cfg.get("admin_username", "admin")
    admin_pass = admin_cfg.get("admin_password", "admin123")

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == admin_user).first()
        if not admin:
            admin = User(
                username=admin_user,
                password_hash=pwd_context.hash(admin_pass),
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
