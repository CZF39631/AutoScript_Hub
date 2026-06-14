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


# Database
DATABASE_URL: str = str(_get(
    "database_url",
    "sqlite:///" + os.path.join(BASE_DIR, "autoscript.db"),
    env_var="DATABASE_URL",
))

# JWT
JWT_SECRET: str = str(_get("jwt_secret", "autoscript-dev-secret-change-in-prod", env_var="JWT_SECRET"))
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 60 * 24

# Storage
STORAGE_DIR: str = _resolve_path(str(_get("storage_dir", os.path.join(BASE_DIR, "storage"))))
SCRIPTS_DIR: str = _resolve_path(str(_get("scripts_dir", os.path.join(STORAGE_DIR, "scripts"))))
LOGS_DIR: str = _resolve_path(str(_get("logs_dir", os.path.join(STORAGE_DIR, "logs"))))

# Log retention & cleanup (design §5.12)
LOG_RETENTION_DAYS: int = int(_get("log_retention_days", 30))
LOG_CLEANUP_HOUR: int = int(_get("log_cleanup_hour", 3))  # daily cleanup at 03:00
LOG_ARCHIVE_DIR: str = _resolve_path(str(_get("log_archive_dir", os.path.join(LOGS_DIR, "archive"))))
LOG_ARCHIVE_RETENTION_DAYS: int = int(_get("log_archive_retention_days", 90))

# Server
BACKEND_HOST: str = str(_get("backend_host", "127.0.0.1"))
BACKEND_PORT: int = int(_get("backend_port", 8000, env_var="BACKEND_PORT"))

# Ensure directories exist
os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(LOG_ARCHIVE_DIR, exist_ok=True)
