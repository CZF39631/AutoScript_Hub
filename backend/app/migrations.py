"""Alembic ownership and safe adoption of pre-0.9 SQLite databases."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.models import Base


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_REVISION = "0001_current_schema"
KNOWN_LEGACY_TABLES = {
    "users",
    "scripts",
    "script_versions",
    "runs",
    "user_scripts",
    "environments",
    "audit_logs",
    "issues",
}
LEGACY_ADDED_COLUMNS = {
    "runs": {"environment_id", "agent_id"},
    "environments": {"python_version", "venv_path", "venv_status", "python_executable"},
    "issues": {"script_version", "log_snapshot", "resolved_version"},
}


class UnsupportedLegacySchema(RuntimeError):
    """Raised before mutation when an existing database is not a known product schema."""


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _adopt_known_legacy_database(config: Config, database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if not tables or "alembic_version" in tables:
            return
        if not KNOWN_LEGACY_TABLES.issubset(tables):
            missing = sorted(KNOWN_LEGACY_TABLES - tables)
            raise UnsupportedLegacySchema(
                "Existing database is not a supported AutoScript Hub schema; "
                f"missing tables: {', '.join(missing)}"
            )
        for table_name in sorted(KNOWN_LEGACY_TABLES):
            model_table = Base.metadata.tables[table_name]
            allowed_missing = LEGACY_ADDED_COLUMNS.get(table_name, set())
            required = {
                column.name: column.type
                for column in model_table.columns
                if column.name not in allowed_missing
            }
            actual = {
                column["name"]: column["type"]
                for column in inspector.get_columns(table_name)
            }
            missing_columns = sorted(set(required) - set(actual))
            if missing_columns:
                raise UnsupportedLegacySchema(
                    f"{table_name} missing columns: {', '.join(missing_columns)}"
                )
            incompatible = sorted(
                name
                for name, expected_type in required.items()
                if actual[name]._type_affinity is not expected_type._type_affinity
            )
            if incompatible:
                raise UnsupportedLegacySchema(
                    f"{table_name} has incompatible types: {', '.join(incompatible)}"
                )
    finally:
        engine.dispose()
    command.stamp(config, BASELINE_REVISION)


def migration_status(database_url: str) -> dict:
    config = alembic_config(database_url)
    head = ScriptDirectory.from_config(config).get_current_head()
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    return {"current": current, "head": head, "ready": current == head and current is not None}


def upgrade_database(database_url: str) -> str:
    config = alembic_config(database_url)
    _adopt_known_legacy_database(config, database_url)
    command.upgrade(config, "head")
    return migration_status(database_url)["current"]
