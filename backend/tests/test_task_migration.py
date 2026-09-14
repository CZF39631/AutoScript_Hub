"""0007 新库、已建表、老库和半成品补列验证。"""
from alembic import command
from sqlalchemy import create_engine, inspect, text
from app.migrations import alembic_config

TABLES = ("task_devices", "device_grants", "scheduled_tasks", "task_executions", "local_run_imports")


def test_task_migration_fresh_metadata_and_repeat(tmp_path):
    url = "sqlite:///" + str(tmp_path / "fresh.db")
    config = alembic_config(url)
    command.upgrade(config, "0007_task_scheduling")
    command.upgrade(config, "0007_task_scheduling")
    engine = create_engine(url)
    try:
        assert set(TABLES).issubset(inspect(engine).get_table_names())
        constraints = inspect(engine).get_unique_constraints("task_executions")
        assert {"uq_task_occurrence", "uq_task_request"}.issubset({c["name"] for c in constraints})
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA integrity_check")).scalar() == "ok"
    finally:
        engine.dispose()


def test_task_migration_existing_old_database_and_safe_downgrade(tmp_path):
    url = "sqlite:///" + str(tmp_path / "old.db")
    config = alembic_config(url)
    command.upgrade(config, "0006_diagnostic_policy")
    engine = create_engine(url)
    with engine.begin() as conn:
        for table in reversed(TABLES):
            conn.execute(text("DROP TABLE " + table))
        conn.execute(text("INSERT INTO users (id,username,password_hash,display_name,role,status,auth_source,created_at,updated_at,is_deleted) VALUES (1,'preserved','unused','保留','operator','active','local',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)"))
    engine.dispose()
    command.upgrade(config, "0007_task_scheduling")
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM users WHERE id=1")).scalar() == "preserved"
    engine.dispose()
    command.downgrade(config, "0006_diagnostic_policy")
    engine = create_engine(url)
    assert not set(TABLES).intersection(inspect(engine).get_table_names())
    engine.dispose()
    command.upgrade(config, "0007_task_scheduling")


def test_task_migration_partial_tables_adds_missing_columns(tmp_path):
    url = "sqlite:///" + str(tmp_path / "partial.db")
    config = alembic_config(url)
    command.upgrade(config, "0006_diagnostic_policy")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE task_devices DROP COLUMN active_execution_id"))
        conn.execute(text("ALTER TABLE task_executions DROP COLUMN stopped"))
        conn.execute(text("ALTER TABLE task_executions DROP COLUMN claimed_at"))
        conn.execute(text("ALTER TABLE scheduled_tasks DROP COLUMN requires_browser"))
    engine.dispose()
    command.upgrade(config, "0007_task_scheduling")
    engine = create_engine(url)
    try:
        assert "active_execution_id" in {c["name"] for c in inspect(engine).get_columns("task_devices")}
        assert {"stopped", "claimed_at"}.issubset({c["name"] for c in inspect(engine).get_columns("task_executions")})
        assert "requires_browser" in {c["name"] for c in inspect(engine).get_columns("scheduled_tasks")}
    finally:
        engine.dispose()
