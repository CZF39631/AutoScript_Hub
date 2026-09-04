from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.migrations import (
    alembic_config,
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
    assert {
        "users", "scripts", "runs", "agents", "user_presets", "user_settings",
        "groups", "user_groups", "script_groups", "server_settings", "alembic_version",
    }.issubset(tables)


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
        default_groups = connection.execute(text(
            "SELECT COUNT(*) FROM groups WHERE is_default=1 AND status='active' AND is_deleted=0"
        )).scalar()
        user_memberships = connection.execute(text("SELECT COUNT(*) FROM user_groups")).scalar()
        script_memberships = connection.execute(text("SELECT COUNT(*) FROM script_groups")).scalar()
    assert count == 1
    assert run == "succeeded"
    assert default_groups == 1
    assert user_memberships == 1
    assert script_memberships == 1
    assert migration_status(database_url)["ready"] is True


def test_group_migration_recovers_an_existing_default_name(tmp_path):
    database_url = _sqlite_url(tmp_path / "existing-group-name.db")
    config = alembic_config(database_url)
    command.upgrade(config, "0003_external_auth_identity")
    with create_engine(database_url).begin() as connection:
        connection.execute(text(
            "INSERT INTO groups "
            "(name, description, status, is_default, created_at, updated_at, is_deleted) "
            "VALUES ('默认分组', 'old', 'disabled', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))

    command.upgrade(config, "head")

    with create_engine(database_url).connect() as connection:
        row = connection.execute(text(
            "SELECT status, is_default, is_deleted FROM groups WHERE name='默认分组'"
        )).one()
        defaults = connection.execute(text(
            "SELECT COUNT(*) FROM groups WHERE is_default=true AND is_deleted=false"
        )).scalar()
    assert tuple(row) == ("active", 1, 0)
    assert defaults == 1


def test_server_settings_migration_seeds_singleton_and_constraints(tmp_path):
    database_url = _sqlite_url(tmp_path / "server-settings.db")
    config = alembic_config(database_url)
    command.upgrade(config, "0004_grouped_marketplace")
    # 0001 uses current metadata for fresh installs; dropping the table here
    # reproduces an existing deployment created before 0005.
    with create_engine(database_url).begin() as connection:
        connection.execute(text("DROP TABLE server_settings"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT id, enabled, outbound_proxy, github_repository, interval_hours "
            "FROM server_settings"
        )).one()
        assert tuple(row) == (1, 0, None, "CZF39631/AutoScript_Hub", 6)
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO server_settings "
                "(id, enabled, github_repository, interval_hours, updated_at) "
                "VALUES (2, 0, 'owner/repo', 6, CURRENT_TIMESTAMP)"
            ))
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(text("UPDATE server_settings SET interval_hours=169 WHERE id=1"))


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
