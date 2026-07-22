from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.migrations import (
    UnsupportedLegacySchema,
    migration_status,
    upgrade_database,
)


LEGACY_SCHEMA = Path(__file__).with_name("fixtures") / "pre_090_schema.sql"


def _sqlite_url(path: Path) -> str:
    return "sqlite:///{}".format(path)


def test_fresh_database_upgrades_to_head(tmp_path):
    database_url = _sqlite_url(tmp_path / "fresh.db")

    revision = upgrade_database(database_url)
    status = migration_status(database_url)
    tables = set(inspect(create_engine(database_url)).get_table_names())

    assert revision == status["head"] == status["current"]
    assert status["ready"] is True
    assert {"users", "scripts", "runs", "agents", "user_presets", "user_settings", "alembic_version"}.issubset(tables)


def test_existing_known_database_is_adopted_without_losing_rows(tmp_path):
    database_url = _sqlite_url(tmp_path / "legacy.db")
    engine = create_engine(database_url)
    raw = engine.raw_connection()
    try:
        raw.executescript(LEGACY_SCHEMA.read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()
    engine.dispose()

    upgrade_database(database_url)

    with create_engine(database_url).connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM users WHERE username='existing'")).scalar()
        run = connection.execute(text("SELECT status FROM runs WHERE id=1")).scalar()
    assert count == 1
    assert run == "succeeded"
    assert migration_status(database_url)["ready"] is True


def test_legacy_schema_missing_required_column_is_rejected_before_stamp(tmp_path):
    database_url = _sqlite_url(tmp_path / "missing-column.db")
    engine = create_engine(database_url)
    raw = engine.raw_connection()
    try:
        raw.executescript(LEGACY_SCHEMA.read_text(encoding="utf-8"))
        raw.executescript("DROP TABLE users; CREATE TABLE users (id INTEGER PRIMARY KEY);")
        raw.commit()
    finally:
        raw.close()
    engine.dispose()

    with pytest.raises(UnsupportedLegacySchema, match="users.*missing columns"):
        upgrade_database(database_url)

    assert "alembic_version" not in inspect(create_engine(database_url)).get_table_names()


def test_legacy_schema_with_incompatible_column_type_is_rejected_before_stamp(tmp_path):
    database_url = _sqlite_url(tmp_path / "wrong-type.db")
    engine = create_engine(database_url)
    raw = engine.raw_connection()
    try:
        raw.executescript(LEGACY_SCHEMA.read_text(encoding="utf-8"))
        raw.executescript(
            "ALTER TABLE users RENAME TO users_valid; "
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, username INTEGER NOT NULL, password_hash TEXT NOT NULL, "
            "display_name VARCHAR(100) NOT NULL, role VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, "
            "last_login_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
            "created_by INTEGER, updated_by INTEGER, is_deleted BOOLEAN NOT NULL);"
        )
        raw.commit()
    finally:
        raw.close()
    engine.dispose()

    with pytest.raises(UnsupportedLegacySchema, match="users.*incompatible types"):
        upgrade_database(database_url)

    assert "alembic_version" not in inspect(create_engine(database_url)).get_table_names()


def test_unknown_legacy_schema_is_rejected_without_modification(tmp_path):
    database_url = _sqlite_url(tmp_path / "unknown.db")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO unrelated (id) VALUES (7)"))
    engine.dispose()

    with pytest.raises(UnsupportedLegacySchema):
        upgrade_database(database_url)

    with create_engine(database_url).connect() as connection:
        assert connection.execute(text("SELECT id FROM unrelated")).scalar() == 7
    assert "alembic_version" not in inspect(create_engine(database_url)).get_table_names()
