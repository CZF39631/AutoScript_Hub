"""Add managed device groups and auditable batch operations."""

from alembic import op
import sqlalchemy as sa


revision = "0011_managed_agent_scale"
down_revision = "0010_agent_thumbnail_capture_pause"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "managed_agent_groups" not in tables:
        op.create_table(
            "managed_agent_groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_managed_agent_groups_name"),
        )
        op.create_index("ix_managed_agent_groups_id", "managed_agent_groups", ["id"])

    if "managed_agent_group_members" not in tables:
        op.create_table(
            "managed_agent_group_members",
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
            sa.ForeignKeyConstraint(["group_id"], ["managed_agent_groups.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("agent_id", "group_id"),
        )
        op.create_index(
            "ix_managed_agent_group_members_group_id",
            "managed_agent_group_members", ["group_id"], unique=False,
        )

    if "managed_agent_batches" not in tables:
        op.create_table(
            "managed_agent_batches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("operation", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
            sa.Column("selection_json", sa.Text(), nullable=False),
            sa.Column("request_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("created_by", "idempotency_key", name="uq_managed_agent_batch_actor_key"),
        )
        op.create_index("ix_managed_agent_batches_id", "managed_agent_batches", ["id"])
        op.create_index(
            "ix_managed_agent_batches_actor_created",
            "managed_agent_batches", ["created_by", "created_at"], unique=False,
        )

    if "managed_agent_batch_items" not in tables:
        op.create_table(
            "managed_agent_batch_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("result", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("detail_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["batch_id"], ["managed_agent_batches.id"]),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("batch_id", "agent_id", name="uq_managed_agent_batch_item"),
        )
        op.create_index("ix_managed_agent_batch_items_id", "managed_agent_batch_items", ["id"])
        op.create_index(
            "ix_managed_agent_batch_items_batch_result",
            "managed_agent_batch_items", ["batch_id", "result"], unique=False,
        )


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in (
        "managed_agent_batch_items", "managed_agent_batches",
        "managed_agent_group_members", "managed_agent_groups",
    ):
        if table in tables:
            op.drop_table(table)
