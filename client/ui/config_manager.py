"""Read/write client configuration from client_config.json."""
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")

DEFAULT_CONFIG = {
    "server_url": "http://127.0.0.1:8000",
    "username": "",
    "password": "",
    "script_download_dir": "",
    "output_dir": "",
    "default_browser_path": "",
    "browser_debug_port": 9222,
    "proxy": "",
    "version": "1.0.0",
    "setup_completed": False,
}


def load_config():
    """Load client config, returning defaults for missing keys."""
    config = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config):
    """Write config dict to client_config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def is_setup_complete():
    """Check if the first-run wizard has been completed."""
    return bool(load_config().get("setup_completed"))


def reset_config():
    """Delete client_config.json to force re-running wizard."""
    if os.path.isfile(CONFIG_PATH):
        os.remove(CONFIG_PATH)
