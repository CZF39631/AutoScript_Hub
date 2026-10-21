"""Add resumable managed batches and managed-device list index."""

from alembic import op
import sqlalchemy as sa


revision = "0013_managed_batch_recovery"
down_revision = "0012_managed_schedule_missed"
branch_labels = None
depends_on = None


_BATCH_COLUMNS = {
    "updated_at": sa.Column("updated_at", sa.DateTime(), nullable=True),
    "lease_expires_at": sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
    "last_error": sa.Column("last_error", sa.Text(), nullable=True),
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    batch_columns = {
        column["name"] for column in inspector.get_columns("managed_agent_batches")
    }
    with op.batch_alter_table("managed_agent_batches") as batch:
        for name, column in _BATCH_COLUMNS.items():
            if name not in batch_columns:
                batch.add_column(column)

    # Existing rows predate leases. Their creation time is the safest durable
    # approximation for updated_at and leaves unfinished rows immediately resumable.
    bind.execute(sa.text(
        "UPDATE managed_agent_batches SET updated_at = created_at WHERE updated_at IS NULL"
    ))
    with op.batch_alter_table("managed_agent_batches") as batch:
        batch.alter_column(
            "updated_at", existing_type=sa.DateTime(), nullable=False,
        )

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("agents")}
    if "ix_agents_managed_list" not in indexes:
        op.create_index(
            "ix_agents_managed_list",
            "agents",
            ["mode", "is_deleted", "enabled", "status", "last_heartbeat"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("agents")}
    if "ix_agents_managed_list" in indexes:
        op.drop_index("ix_agents_managed_list", table_name="agents")

    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("managed_agent_batches")
    }
    with op.batch_alter_table("managed_agent_batches") as batch:
        for name in ("last_error", "lease_expires_at", "updated_at"):
            if name in columns:
                batch.drop_column(name)
