"""Adopt known pre-0.9 databases and add release-era fields."""

from alembic import op
import sqlalchemy as sa

from app.models import Base
from app.routers.settings import UserSettings  # noqa: F401 - registers metadata


revision = "0002_adopt_release_090"
down_revision = "0001_current_schema"
branch_labels = None
depends_on = None


_COLUMNS = {
    "runs": [
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), nullable=True),
    ],
    "environments": [
        sa.Column("python_version", sa.String(length=20), nullable=True),
        sa.Column("venv_path", sa.String(length=500), nullable=True),
        sa.Column("venv_status", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("python_executable", sa.String(length=500), nullable=True),
    ],
    "issues": [
        sa.Column("script_version", sa.Integer(), nullable=True),
        sa.Column("log_snapshot", sa.Text(), nullable=True),
        sa.Column("resolved_version", sa.Integer(), nullable=True),
    ],
}


def upgrade():
    bind = op.get_bind()
    # Creates tables introduced after the earliest known schema, without touching existing ones.
    Base.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table_name, columns in _COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {item["name"] for item in inspector.get_columns(table_name)}
        for column in columns:
            if column.name not in existing_columns:
                op.add_column(table_name, column.copy())


def downgrade():
    # Adoption is intentionally irreversible: a rollback restores the pre-upgrade backup.
    pass
