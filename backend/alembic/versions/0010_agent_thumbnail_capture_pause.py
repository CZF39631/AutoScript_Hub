"""Persist the device-controlled thumbnail capture pause state."""

from alembic import op
import sqlalchemy as sa


revision = "0010_agent_thumbnail_capture_pause"
down_revision = "0009_run_retry_lineage"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("agents")}
    if "thumbnail_capture_paused" not in columns:
        with op.batch_alter_table("agents") as batch:
            batch.add_column(
                sa.Column(
                    "thumbnail_capture_paused",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("agents")}
    if "thumbnail_capture_paused" in columns:
        with op.batch_alter_table("agents") as batch:
            batch.drop_column("thumbnail_capture_paused")
