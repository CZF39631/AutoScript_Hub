#!/usr/bin/env python3
"""Create, verify, and restore bounded AutoScript Hub data backups."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile


def _root(value):
    root = Path(value).expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("data directory cannot be a filesystem root")
    return root


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_database_revision(connection):
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError:
        return "unversioned"
    return str(row[0]) if row and row[0] else "unversioned"


def _database_revision(path):
    with closing(sqlite3.connect(path)) as connection:
        return _read_database_revision(connection)


def create_backup(data_dir, version):
    data = _root(data_dir)
    source_db = data / "autoscript.db"
    if not source_db.is_file():
        raise FileNotFoundError(f"database not found: {source_db}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = data / "backups" / f"{stamp}-{version}"
    destination.mkdir(parents=True, exist_ok=False)

    database_copy = destination / "autoscript.db"
    with closing(sqlite3.connect(source_db)) as source, closing(sqlite3.connect(database_copy)) as target:
        source.backup(target)
        database_revision = _read_database_revision(target)

    artifacts = [database_copy]
    scripts = data / "scripts"
    if scripts.is_dir():
        archive = destination / "scripts.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(scripts, arcname="scripts")
        artifacts.append(archive)

    manifest = {
        "schema_version": 2,
        "application_version": version,
        "database_revision": database_revision,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            item.name: {"size": item.stat().st_size, "sha256": _sha256(item)}
            for item in artifacts
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(destination)


def verify_backup(backup_dir):
    backup = Path(backup_dir).resolve()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in {1, 2}:
        raise ValueError("unsupported backup manifest version")
    for name, expected in manifest["files"].items():
        artifact = backup / name
        if not artifact.is_file() or artifact.stat().st_size != expected["size"] or _sha256(artifact) != expected["sha256"]:
            raise ValueError(f"backup verification failed: {name}")
    if manifest["schema_version"] == 2:
        actual_revision = _database_revision(backup / "autoscript.db")
        if actual_revision != manifest.get("database_revision"):
            raise ValueError("backup database revision does not match manifest")
    print("verified")


def _safe_extract(archive, destination):
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if destination not in target.parents and target != destination:
                raise ValueError(f"unsafe archive member: {member.name}")
        bundle.extractall(destination)


def _remove_path(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def restore_backup(backup_dir, data_dir):
    verify_backup(backup_dir)
    backup = Path(backup_dir).resolve()
    data = _root(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    staging_root = data / "tmp"
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autoscript-restore-", dir=staging_root) as staging_value:
        staging = Path(staging_value)
        shutil.copy2(backup / "autoscript.db", staging / "autoscript.db")
        if (backup / "scripts.tar.gz").is_file():
            _safe_extract(backup / "scripts.tar.gz", staging)

        database = data / "autoscript.db"
        database_new = data / "autoscript.db.restore-new"
        database_previous = data / "autoscript.db.restore-previous"
        scripts = data / "scripts"
        scripts_new = data / "scripts.restore-new"
        scripts_previous = data / "scripts.restore-previous"
        restore_scripts = (staging / "scripts").is_dir()

        for path in (database_new, database_previous, scripts_new, scripts_previous):
            _remove_path(path)
        shutil.copy2(staging / "autoscript.db", database_new)
        if restore_scripts:
            shutil.copytree(staging / "scripts", scripts_new)

        had_database = database.exists()
        had_scripts = scripts.exists()
        database_previous_created = False
        database_installed = False
        scripts_previous_created = False
        scripts_installed = False
        try:
            if had_database:
                database.replace(database_previous)
                database_previous_created = True
            database_new.replace(database)
            database_installed = True
            if restore_scripts:
                if had_scripts:
                    scripts.replace(scripts_previous)
                    scripts_previous_created = True
                scripts_new.replace(scripts)
                scripts_installed = True
        except Exception:
            if database_installed:
                _remove_path(database)
            if database_previous_created:
                database_previous.replace(database)
            if restore_scripts:
                if scripts_installed:
                    _remove_path(scripts)
                if scripts_previous_created:
                    scripts_previous.replace(scripts)
            _remove_path(database_new)
            _remove_path(scripts_new)
            raise
        else:
            _remove_path(database_previous)
            _remove_path(scripts_previous)
    print("restored")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--data-dir", required=True)
    backup.add_argument("--version", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    if args.command == "backup":
        create_backup(args.data_dir, args.version)
    elif args.command == "verify":
        verify_backup(args.backup)
    else:
        restore_backup(args.backup, args.data_dir)


if __name__ == "__main__":
    main()
