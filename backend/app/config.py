import os
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT: str = os.path.dirname(BASE_DIR)

# Load config.json if exists
_config: Dict[str, Any] = {}
_config_path: str = os.path.join(PROJECT_ROOT, "config.json")
if os.path.isfile(_config_path):
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            _config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load config.json: %s", e)


def _resolve_path(p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.join(PROJECT_ROOT, p)


def _get(key: str, default: Any = None, env_var: Optional[str] = None) -> Any:
    if env_var and os.environ.get(env_var):
        return os.environ.get(env_var)
    return _config.get(key, default)


def _get_path(key: str, default: str, env_var: str) -> str:
    return os.path.abspath(_resolve_path(str(_get(key, default, env_var=env_var))))


def _get_runtime_path(key: str, default: str, env_var: str) -> str:
    """Resolve data paths without leaking legacy config into a DATA_DIR deployment."""
    explicit = os.environ.get(env_var)
    if explicit:
        value = explicit
    elif os.environ.get("DATA_DIR"):
        value = default
    else:
        value = _config.get(key, default)
    return os.path.abspath(_resolve_path(str(value)))


def _get_csv(key: str, default: str, env_var: str) -> list[str]:
    value = _get(key, default, env_var=env_var)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


# Runtime data root. Release containers set this to /data.
DATA_DIR: str = _get_path("data_dir", BASE_DIR, "DATA_DIR")


# Database
DATABASE_URL: str = str(_get(
    "database_url",
    "sqlite:///" + os.path.join(DATA_DIR, "autoscript.db"),
    env_var="DATABASE_URL",
))
if os.environ.get("DATA_DIR") and not os.environ.get("DATABASE_URL"):
    DATABASE_URL = "sqlite:///" + os.path.join(DATA_DIR, "autoscript.db")

# JWT
JWT_SECRET: str = str(_get("jwt_secret", "autoscript-dev-secret-change-in-prod", env_var="JWT_SECRET"))
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 60 * 24

# First-start administrator. These values are read only when the users table is empty.
ADMIN_USERNAME: str = str(_get("admin_username", "admin", env_var="ADMIN_USERNAME"))
ADMIN_PASSWORD: str = str(_get("admin_password", "admin123", env_var="ADMIN_PASSWORD"))

# Storage
STORAGE_DIR: str = _get_runtime_path("storage_dir", DATA_DIR, "STORAGE_DIR")
SCRIPTS_DIR: str = _get_runtime_path("scripts_dir", os.path.join(STORAGE_DIR, "scripts"), "SCRIPTS_DIR")
LOGS_DIR: str = _get_runtime_path("logs_dir", os.path.join(STORAGE_DIR, "logs"), "LOGS_DIR")
BACKUPS_DIR: str = _get_runtime_path("backups_dir", os.path.join(DATA_DIR, "backups"), "BACKUPS_DIR")

# Log retention & cleanup (design §5.12)
LOG_LEVEL: str = str(_get("log_level", "INFO", env_var="LOG_LEVEL")).upper()
LOG_RETENTION_DAYS: int = int(_get("log_retention_days", 30, env_var="LOG_RETENTION_DAYS"))
LOG_CLEANUP_HOUR: int = int(_get("log_cleanup_hour", 3, env_var="LOG_CLEANUP_HOUR"))
LOG_ARCHIVE_DIR: str = _get_path("log_archive_dir", os.path.join(LOGS_DIR, "archive"), "LOG_ARCHIVE_DIR")
LOG_ARCHIVE_RETENTION_DAYS: int = int(
    _get("log_archive_retention_days", 90, env_var="LOG_ARCHIVE_RETENTION_DAYS")
)

# Server
BACKEND_HOST: str = str(_get("backend_host", "127.0.0.1", env_var="BACKEND_HOST"))
BACKEND_PORT: int = int(_get("backend_port", 8000, env_var="BACKEND_PORT"))
CORS_ORIGINS: list[str] = _get_csv("cors_origins", "", "CORS_ORIGINS")

# Ensure directories exist
os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(LOG_ARCHIVE_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)
