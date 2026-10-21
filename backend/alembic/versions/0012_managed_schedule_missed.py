"""Expose the latest missed managed schedule occurrence."""

from alembic import op
import sqlalchemy as sa


revision = "0012_managed_schedule_missed"
down_revision = "0011_managed_agent_scale"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("managed_schedules")
    }
    with op.batch_alter_table("managed_schedules") as batch:
        if "last_missed_at" not in columns:
            batch.add_column(sa.Column("last_missed_at", sa.DateTime(), nullable=True))
        if "last_missed_reason" not in columns:
            batch.add_column(sa.Column("last_missed_reason", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("managed_schedules")
    }
    with op.batch_alter_table("managed_schedules") as batch:
        if "last_missed_reason" in columns:
            batch.drop_column("last_missed_reason")
        if "last_missed_at" in columns:
            batch.drop_column("last_missed_at")
