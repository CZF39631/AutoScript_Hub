import importlib.util
import gc
import json
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "server" / "backup_sqlite.py"


def _load_backup_module():
    spec = importlib.util.spec_from_file_location("backup_sqlite", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_marker(database, value):
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT NOT NULL)")
        connection.execute("DELETE FROM marker")
        connection.execute("INSERT INTO marker (value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _read_marker(database):
    connection = sqlite3.connect(database)
    try:
        return connection.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        connection.close()


def test_create_backup_closes_source_and_target_connections(tmp_path, monkeypatch):
    backup_sqlite = _load_backup_module()
    data = tmp_path / "data"
    data.mkdir()
    (data / "autoscript.db").write_bytes(b"source")
    connections = []

    class RecordingConnection:
        def __init__(self, path):
            self.path = Path(path)
            self.closed = False
            connections.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def backup(self, target):
            target.path.write_bytes(b"consistent backup")

        def execute(self, statement):
            assert statement == "SELECT version_num FROM alembic_version"
            return self

        def fetchone(self):
            return None

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        backup_sqlite.sqlite3,
        "connect",
        lambda path: RecordingConnection(path),
    )

    backup_sqlite.create_backup(data, "0.9.0")

    assert len(connections) == 2
    assert all(connection.closed for connection in connections)


def test_backup_manifest_records_alembic_database_revision(tmp_path):
    backup_sqlite = _load_backup_module()
    data = tmp_path / "data"
    data.mkdir()
    database = data / "autoscript.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            ("0002_adopt_release_090",),
        )
        connection.commit()
    finally:
        connection.close()

    backup_sqlite.create_backup(data, "0.9.0")
    backup = next((data / "backups").iterdir())
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["database_revision"] == "0002_adopt_release_090"


def test_restore_stages_inside_writable_data_directory(tmp_path, monkeypatch):
    backup_sqlite = _load_backup_module()
    data = tmp_path / "data"
    scripts = data / "scripts"
    scripts.mkdir(parents=True)
    database = data / "autoscript.db"
    _write_marker(database, "before-backup")
    (scripts / "sample.py").write_text("original\n", encoding="utf-8")

    backup_sqlite.create_backup(data, "0.9.0")
    backup = next((data / "backups").iterdir())

    gc.collect()
    database.unlink()
    (scripts / "sample.py").write_text("changed\n", encoding="utf-8")

    original_temporary_directory = backup_sqlite.tempfile.TemporaryDirectory
    observed = {}

    def recording_temporary_directory(*args, **kwargs):
        observed["dir"] = Path(kwargs["dir"])
        return original_temporary_directory(*args, **kwargs)

    monkeypatch.setattr(
        backup_sqlite.tempfile,
        "TemporaryDirectory",
        recording_temporary_directory,
    )

    backup_sqlite.restore_backup(backup, data)

    assert observed["dir"] == data / "tmp"
    assert _read_marker(database) == "before-backup"
    assert (scripts / "sample.py").read_text(encoding="utf-8") == "original\n"


def test_restore_failure_rolls_database_and_scripts_back_together(tmp_path, monkeypatch):
    backup_sqlite = _load_backup_module()
    data = tmp_path / "data"
    scripts = data / "scripts"
    scripts.mkdir(parents=True)
    database = data / "autoscript.db"
    _write_marker(database, "backup-state")
    (scripts / "sample.py").write_text("backup-script\n", encoding="utf-8")
    backup_sqlite.create_backup(data, "0.9.0")
    backup = next((data / "backups").iterdir())

    _write_marker(database, "current-state")
    (scripts / "sample.py").write_text("current-script\n", encoding="utf-8")
    original_replace = backup_sqlite.Path.replace

    def fail_when_committing_new_scripts(path, target):
        if path.name == "scripts.restore-new" and Path(target).name == "scripts":
            raise OSError("injected script swap failure")
        return original_replace(path, target)

    monkeypatch.setattr(backup_sqlite.Path, "replace", fail_when_committing_new_scripts)

    with pytest.raises(OSError, match="injected"):
        backup_sqlite.restore_backup(backup, data)

    assert _read_marker(database) == "current-state"
    assert (scripts / "sample.py").read_text(encoding="utf-8") == "current-script\n"


def test_database_commit_failure_does_not_remove_untouched_scripts(tmp_path, monkeypatch):
    backup_sqlite = _load_backup_module()
    data = tmp_path / "data"
    scripts = data / "scripts"
    scripts.mkdir(parents=True)
    database = data / "autoscript.db"
    _write_marker(database, "backup-state")
    (scripts / "sample.py").write_text("backup-script\n", encoding="utf-8")
    backup_sqlite.create_backup(data, "0.9.0")
    backup = next((data / "backups").iterdir())

    _write_marker(database, "current-state")
    (scripts / "sample.py").write_text("current-script\n", encoding="utf-8")
    original_replace = backup_sqlite.Path.replace

    def fail_when_committing_new_database(path, target):
        if path.name == "autoscript.db.restore-new" and Path(target).name == "autoscript.db":
            raise OSError("injected database swap failure")
        return original_replace(path, target)

    monkeypatch.setattr(backup_sqlite.Path, "replace", fail_when_committing_new_database)

    with pytest.raises(OSError, match="injected"):
        backup_sqlite.restore_backup(backup, data)

    assert _read_marker(database) == "current-state"
    assert (scripts / "sample.py").read_text(encoding="utf-8") == "current-script\n"
