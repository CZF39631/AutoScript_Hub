import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Load config.json if exists
_config = {}
_config_path = os.path.join(PROJECT_ROOT, "config.json")
if os.path.isfile(_config_path):
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            _config = json.load(f)
    except Exception:
        pass


def _resolve_path(p):
    if os.path.isabs(p):
        return p
    return os.path.join(PROJECT_ROOT, p)


def _get(key, default=None, env_var=None):
    if env_var and os.environ.get(env_var):
        return os.environ.get(env_var)
    return _config.get(key, default)


# Database
DATABASE_URL = _get(
    "database_url",
    "sqlite:///" + os.path.join(BASE_DIR, "autoscript.db"),
    env_var="DATABASE_URL",
)

# JWT
JWT_SECRET = _get("jwt_secret", "autoscript-dev-secret-change-in-prod", env_var="JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24

# Storage
STORAGE_DIR = _resolve_path(_get("storage_dir", os.path.join(BASE_DIR, "storage")))
SCRIPTS_DIR = _resolve_path(_get("scripts_dir", os.path.join(STORAGE_DIR, "scripts")))
LOGS_DIR = _resolve_path(_get("logs_dir", os.path.join(STORAGE_DIR, "logs")))

# Server
BACKEND_HOST = _get("backend_host", "127.0.0.1")
BACKEND_PORT = int(_get("backend_port", 8000, env_var="BACKEND_PORT"))

# Ensure directories exist
os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
