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
        "groups", "user_groups", "script_groups", "server_settings",
        "managed_schedules", "managed_agent_groups", "managed_agent_group_members",
        "managed_agent_batches", "managed_agent_batch_items", "alembic_version",
    }.issubset(tables)
    inspector = inspect(create_engine(database_url))
    assert {
        "device_uid", "mode", "enabled", "agent_token_issued_at",
        "thumbnail_updated_at", "thumbnail_size", "thumbnail_capture_paused",
    }.issubset(
        {column["name"] for column in inspector.get_columns("agents")}
    )
    assert {
        "target_agent_id", "requested_by", "dispatch_type", "schedule_id",
        "retry_of_run_id", "scheduled_for", "expires_at", "claimed_at",
    }.issubset({column["name"] for column in inspector.get_columns("runs")})
    assert {"updated_at", "lease_expires_at", "last_error"}.issubset(
        {column["name"] for column in inspector.get_columns("managed_agent_batches")}
    )
    assert "ix_agents_managed_list" in {
        index["name"] for index in inspector.get_indexes("agents")
    }


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


def test_thumbnail_migration_upgrades_0006_and_downgrades_cleanly(tmp_path):
    database_url = _sqlite_url(tmp_path / "agent-thumbnails.db")
    config = alembic_config(database_url)
    command.upgrade(config, "0006_managed_agent_mode")
    # 0001 intentionally builds current metadata on brand-new databases. Remove
    # the future columns to reproduce a deployment whose real head is 0006.
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE agents DROP COLUMN thumbnail_updated_at"))
        connection.execute(text("ALTER TABLE agents DROP COLUMN thumbnail_size"))
    before = {column["name"] for column in inspect(engine).get_columns("agents")}
    assert "thumbnail_updated_at" not in before
    assert "thumbnail_size" not in before
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    after = {column["name"] for column in inspect(engine).get_columns("agents")}
    assert {"thumbnail_updated_at", "thumbnail_size"}.issubset(after)
    engine.dispose()

    command.downgrade(config, "0006_managed_agent_mode")
    engine = create_engine(database_url)
    downgraded = {column["name"] for column in inspect(engine).get_columns("agents")}
    assert "thumbnail_updated_at" not in downgraded
    assert "thumbnail_size" not in downgraded
    engine.dispose()


def test_retry_lineage_migration_upgrades_0008_and_downgrades_cleanly(tmp_path):
    database_url = _sqlite_url(tmp_path / "run-retry-lineage.db")
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0008_managed_schedule_cron")
    engine = create_engine(database_url)
    assert "retry_of_run_id" not in {
        column["name"] for column in inspect(engine).get_columns("runs")
    }
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "retry_of_run_id" in {
        column["name"] for column in inspect(engine).get_columns("runs")
    }
    assert "ix_runs_retry_of_run_id" in {
        index["name"] for index in inspect(engine).get_indexes("runs")
    }
    engine.dispose()

    command.downgrade(config, "0008_managed_schedule_cron")
    engine = create_engine(database_url)
    assert "retry_of_run_id" not in {
        column["name"] for column in inspect(engine).get_columns("runs")
    }
    engine.dispose()


def test_thumbnail_pause_migration_upgrades_0009_and_downgrades_cleanly(tmp_path):
    database_url = _sqlite_url(tmp_path / "agent-thumbnail-pause.db")
    config = alembic_config(database_url)
    command.upgrade(config, "0009_run_retry_lineage")
    # Fresh 0001 uses current metadata; remove the future column to reproduce a
    # deployed database whose actual head is 0009.
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE agents DROP COLUMN thumbnail_capture_paused"))
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"]: column for column in inspect(engine).get_columns("agents")}
    assert columns["thumbnail_capture_paused"]["nullable"] is False
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users "
            "(id, username, password_hash, auth_source, display_name, role, status, "
            "created_at, updated_at, is_deleted) VALUES "
            "(1, 'owner', 'hash', 'local', 'Owner', 'operator', 'active', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
        connection.execute(text(
            "INSERT INTO agents "
            "(id, device_uid, machine_name, user_id, mode, enabled, status, "
            "created_at, updated_at, is_deleted) VALUES "
            "(1, 'pause-default', 'pc', 1, 'managed', 1, 'online', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
        assert connection.execute(text(
            "SELECT thumbnail_capture_paused FROM agents WHERE id=1"
        )).scalar() == 0
    engine.dispose()

    command.downgrade(config, "0009_run_retry_lineage")
    engine = create_engine(database_url)
    assert "thumbnail_capture_paused" not in {
        column["name"] for column in inspect(engine).get_columns("agents")
    }
    engine.dispose()


def test_managed_scale_migration_upgrades_0010_and_downgrades_cleanly(tmp_path):
    database_url = _sqlite_url(tmp_path / "managed-scale.db")
    config = alembic_config(database_url)
    command.upgrade(config, "0010_agent_thumbnail_capture_pause")
    engine = create_engine(database_url)
    # Fresh 0001 uses current metadata, so remove future tables to reproduce a deployed 0010 database.
    with engine.begin() as connection:
        for table in (
            "managed_agent_batch_items", "managed_agent_batches",
            "managed_agent_group_members", "managed_agent_groups",
        ):
            connection.execute(text("DROP TABLE IF EXISTS {}".format(table)))
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "managed_agent_groups", "managed_agent_group_members",
        "managed_agent_batches", "managed_agent_batch_items",
    }.issubset(tables)
    assert "uq_managed_agent_batch_actor_key" in {
        item["name"] for item in inspect(engine).get_unique_constraints("managed_agent_batches")
    }
    engine.dispose()

    command.downgrade(config, "0010_agent_thumbnail_capture_pause")
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert "managed_agent_groups" not in tables
    assert "managed_agent_batches" not in tables


def test_managed_schedule_missed_migration_has_clean_upgrade_and_downgrade(tmp_path):
    database_url = _sqlite_url(tmp_path / "managed-schedule-missed.db")
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("managed_schedules")}
    assert {"last_missed_at", "last_missed_reason"}.issubset(columns)
    engine.dispose()

    command.downgrade(config, "0011_managed_agent_scale")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("managed_schedules")}
    assert "last_missed_at" not in columns
    assert "last_missed_reason" not in columns
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("managed_schedules")}
    assert {"last_missed_at", "last_missed_reason"}.issubset(columns)
    engine.dispose()


def test_managed_downgrade_terminates_directed_work_before_dropping_target(tmp_path):
    database_url = _sqlite_url(tmp_path / "managed-downgrade.db")
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users "
            "(id, username, password_hash, auth_source, display_name, role, status, "
            "created_at, updated_at, is_deleted) VALUES "
            "(1, 'owner', 'hash', 'local', 'Owner', 'operator', 'active', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
        connection.execute(text(
            "INSERT INTO scripts "
            "(id, name, type, latest_version, status, created_at, updated_at, is_deleted) "
            "VALUES (1, 'script', 'py', 1, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
        connection.execute(text(
            "INSERT INTO agents "
            "(id, device_uid, machine_name, user_id, mode, enabled, status, "
            "created_at, updated_at, is_deleted) VALUES "
            "(1, 'downgrade-device', 'pc', 1, 'managed', 1, 'online', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
        connection.execute(text(
            "INSERT INTO runs "
            "(id, script_id, script_version, user_id, status, target_agent_id, "
            "dispatch_type, created_at, updated_at, is_deleted) VALUES "
            "(1, 1, 1, 1, 'pending', 1, 'managed_manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
            "(2, 1, 1, 1, 'running', 1, 'managed_manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
    engine.dispose()

    command.downgrade(config, "0005_server_settings")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, status, finished_at, error_msg FROM runs ORDER BY id"
        )).all()
    assert rows[0][1] == "cancelled"
    assert rows[1][1] == "failed"
    assert rows[0][2] is not None and rows[1][2] is not None
    assert "target_agent_id" not in {
        column["name"] for column in inspect(engine).get_columns("runs")
    }
    engine.dispose()


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
