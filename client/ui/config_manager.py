"""Read/write client configuration in the mutable per-user data root."""
import json
import os

from client.runtime.paths import ClientPaths
from shared.version import get_version


_PATHS = ClientPaths.from_environment()
_PATHS.ensure()
PROJECT_ROOT = str(_PATHS.install_dir)
CONFIG_PATH = str(_PATHS.config_file)
LEGACY_CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")

DEFAULT_CONFIG = {
    "server_url": "http://127.0.0.1:8000",
    "username": "",
    "password": "",
    "script_download_dir": "",
    "output_dir": "",
    "default_browser_path": "",
    "browser_debug_port": 9222,
    "proxy": "",
    "pip_index_url": "",
    "github_update_repository": "CZF39631/AutoScript_Hub",
    "update_channel": "beta",
    "update_manifest_urls": [],
    "version": get_version(),
    "setup_completed": False,
}


def load_config():
    """Load client config, returning defaults for missing keys."""
    config = dict(DEFAULT_CONFIG)
    source = CONFIG_PATH if os.path.isfile(CONFIG_PATH) else LEGACY_CONFIG_PATH
    if os.path.isfile(source):
        try:
            with open(source, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    config["version"] = get_version()
    return config


def save_config(config):
    """Atomically write config without touching the installation directory."""
    _PATHS.ensure()
    temporary = CONFIG_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, CONFIG_PATH)


def is_setup_complete():
    """Check if the first-run wizard has been completed."""
    return bool(load_config().get("setup_completed"))


def reset_config():
    """Delete client_config.json to force re-running wizard."""
    if os.path.isfile(CONFIG_PATH):
        os.remove(CONFIG_PATH)
