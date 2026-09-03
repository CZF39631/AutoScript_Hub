"""Read/write client configuration in the mutable per-user data root."""
import json
import logging
import os

from client.runtime.credentials import (
    CredentialStorageError,
    delete_credentials,
    load_credentials,
    save_credentials,
)
from client.runtime.paths import ClientPaths
from shared.version import get_version


logger = logging.getLogger(__name__)

_PATHS = ClientPaths.from_environment()
_PATHS.ensure()
PROJECT_ROOT = str(_PATHS.install_dir)
CONFIG_PATH = str(_PATHS.config_file)
LEGACY_CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")

DEFAULT_CONFIG = {
    "server_url": "http://127.0.0.1:8000",
    "username": "",
    "remember_credentials": False,
    "script_download_dir": "",
    "output_dir": "",
    "default_browser_path": "",
    "browser_debug_port": 9222,
    "proxy": "",
    "pip_index_url": "",
    "gitee_update_repository": "chuzifeng/auto-script_-hub",
    "github_update_repository": "CZF39631/AutoScript_Hub",
    "update_channel": "stable",
    "update_manifest_urls": [],
    "version": get_version(),
    "setup_completed": False,
}


def _read_saved_config():
    source = CONFIG_PATH if os.path.isfile(CONFIG_PATH) else LEGACY_CONFIG_PATH
    if not os.path.isfile(source):
        return {}, source
    try:
        with open(source, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return (saved if isinstance(saved, dict) else {}), source
    except (json.JSONDecodeError, OSError):
        return {}, source


def _write_config(config):
    _PATHS.ensure()
    temporary = CONFIG_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, CONFIG_PATH)


def load_config():
    """Load config and restore any remembered password into memory only."""
    config = dict(DEFAULT_CONFIG)
    saved, source = _read_saved_config()
    config.update(saved)

    # One-time migration from pre-1.1 plaintext passwords to Windows DPAPI.
    plaintext = str(saved.get("password", ""))
    if plaintext and config.get("username"):
        try:
            save_credentials(config["server_url"], config["username"], plaintext)
            persisted = dict(saved)
            persisted.pop("password", None)
            persisted["remember_credentials"] = True
            _write_config(persisted)
            if source == LEGACY_CONFIG_PATH and source != CONFIG_PATH:
                try:
                    os.remove(source)
                except OSError as exc:
                    logger.warning("旧客户端配置中的明文密码未能删除: %s", exc)
            config["remember_credentials"] = True
        except CredentialStorageError:
            # Preserve the old value until secure migration succeeds.
            config["password"] = plaintext
    if config.get("remember_credentials") and config.get("username"):
        config["password"] = load_credentials(config["server_url"], config["username"])
    else:
        config["password"] = plaintext if plaintext else ""
    config["version"] = get_version()
    return config


def save_config(config):
    """Atomically save non-secret config and store remembered passwords via DPAPI."""
    persisted = dict(config)
    password = str(persisted.pop("password", ""))
    server_url = str(persisted.get("server_url", DEFAULT_CONFIG["server_url"]))
    username = str(persisted.get("username", ""))
    remember = bool(persisted.get("remember_credentials", bool(password)))
    persisted["remember_credentials"] = remember

    if remember and password:
        save_credentials(server_url, username, password)
    elif not remember and username:
        delete_credentials(server_url, username)
    _write_config(persisted)


def is_setup_complete():
    """Check if the first-run wizard has been completed."""
    return bool(load_config().get("setup_completed"))


def reset_config():
    """Delete client config and its currently-associated remembered credential."""
    config = load_config()
    if config.get("username"):
        delete_credentials(config.get("server_url", ""), config["username"])
    if os.path.isfile(CONFIG_PATH):
        os.remove(CONFIG_PATH)
