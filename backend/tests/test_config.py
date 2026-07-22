import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"


def _load_config(environment):
    code = """
import json
from app import config

print(json.dumps({
    "data_dir": config.DATA_DIR,
    "database_url": config.DATABASE_URL,
    "storage_dir": config.STORAGE_DIR,
    "scripts_dir": config.SCRIPTS_DIR,
    "logs_dir": config.LOGS_DIR,
    "backups_dir": config.BACKUPS_DIR,
    "admin_username": config.ADMIN_USERNAME,
    "admin_password": config.ADMIN_PASSWORD,
}))
"""
    process_environment = os.environ.copy()
    process_environment.update(environment)
    process_environment["PYTHONPATH"] = str(BACKEND_DIR)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=process_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_data_dir_owns_default_runtime_paths(tmp_path):
    values = _load_config(
        {
            "DATA_DIR": str(tmp_path),
            "DATABASE_URL": "",
            "STORAGE_DIR": "",
            "SCRIPTS_DIR": "",
            "LOGS_DIR": "",
            "BACKUPS_DIR": "",
        }
    )

    assert Path(values["data_dir"]) == tmp_path
    assert values["database_url"] == f"sqlite:///{tmp_path / 'autoscript.db'}"
    assert Path(values["storage_dir"]) == tmp_path
    assert Path(values["scripts_dir"]) == tmp_path / "scripts"
    assert Path(values["logs_dir"]) == tmp_path / "logs"
    assert Path(values["backups_dir"]) == tmp_path / "backups"


def test_runtime_paths_accept_explicit_environment_overrides(tmp_path):
    values = _load_config(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": "sqlite:///custom.db",
            "STORAGE_DIR": str(tmp_path / "storage"),
            "SCRIPTS_DIR": str(tmp_path / "script-files"),
            "LOGS_DIR": str(tmp_path / "log-files"),
            "BACKUPS_DIR": str(tmp_path / "backup-files"),
        }
    )

    assert values["database_url"] == "sqlite:///custom.db"
    assert Path(values["storage_dir"]) == tmp_path / "storage"
    assert Path(values["scripts_dir"]) == tmp_path / "script-files"
    assert Path(values["logs_dir"]) == tmp_path / "log-files"
    assert Path(values["backups_dir"]) == tmp_path / "backup-files"


def test_initial_admin_credentials_are_environment_first(tmp_path):
    values = _load_config(
        {
            "DATA_DIR": str(tmp_path),
            "ADMIN_USERNAME": "lan-admin",
            "ADMIN_PASSWORD": "test-only-password",
        }
    )

    assert values["admin_username"] == "lan-admin"
    assert values["admin_password"] == "test-only-password"
