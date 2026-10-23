"""Add managed Agent identity, directed runs and fixed-interval schedules."""

from alembic import op
import sqlalchemy as sa


revision = "0006_managed_agent_mode"
down_revision = "0005_server_settings"
branch_labels = None
depends_on = None


def _column_names(inspector, table):
    return {item["name"] for item in inspector.get_columns(table)}


def _index_names(inspector, table):
    return {item["name"] for item in inspector.get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "managed_schedules" not in tables:
        op.create_table(
            "managed_schedules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("script_id", sa.Integer(), nullable=False),
            sa.Column("params", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("interval_seconds", sa.Integer(), nullable=False),
            sa.Column("expires_after_seconds", sa.Integer(), nullable=False, server_default="3600"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("next_run_at", sa.DateTime(), nullable=False),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.CheckConstraint("interval_seconds >= 60", name="ck_managed_schedules_interval"),
            sa.CheckConstraint("expires_after_seconds >= 60", name="ck_managed_schedules_expiry"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
            sa.ForeignKeyConstraint(["script_id"], ["scripts.id"]),
            sa.ForeignKeyConstraint(["environment_id"], ["environments.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_managed_schedules_id", "managed_schedules", ["id"], unique=False)
        op.create_index(
            "ix_managed_schedules_due", "managed_schedules", ["enabled", "next_run_at"], unique=False
        )

    inspector = sa.inspect(bind)
    agent_columns = _column_names(inspector, "agents")
    missing_agent_columns = []
    if "device_uid" not in agent_columns:
        missing_agent_columns.append(sa.Column("device_uid", sa.String(length=255), nullable=True))
    if "mode" not in agent_columns:
        missing_agent_columns.append(
            sa.Column("mode", sa.String(length=20), nullable=False, server_default="standard")
        )
    if "enabled" not in agent_columns:
        missing_agent_columns.append(
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
    if "agent_token_issued_at" not in agent_columns:
        # Existing rows remain NULL and receive one token during the one-time
        # legacy upgrade registration path.
        missing_agent_columns.append(sa.Column("agent_token_issued_at", sa.DateTime(), nullable=True))
    if missing_agent_columns:
        with op.batch_alter_table("agents") as batch:
            for column in missing_agent_columns:
                batch.add_column(column)

    rows = bind.execute(sa.text("SELECT id, device_uid FROM agents")).fetchall()
    for row in rows:
        if not row.device_uid:
            bind.execute(
                sa.text("UPDATE agents SET device_uid=:uid WHERE id=:id"),
                {"uid": "legacy-{}".format(row.id), "id": row.id},
            )

    inspector = sa.inspect(bind)
    unique_names = {item.get("name") for item in inspector.get_unique_constraints("agents")}
    check_names = {item.get("name") for item in inspector.get_check_constraints("agents")}
    device_nullable = next(
        item["nullable"] for item in inspector.get_columns("agents") if item["name"] == "device_uid"
    )
    with op.batch_alter_table("agents") as batch:
        if device_nullable:
            batch.alter_column("device_uid", existing_type=sa.String(length=255), nullable=False)
        if "uq_agents_device_uid" not in unique_names:
            batch.create_unique_constraint("uq_agents_device_uid", ["device_uid"])
        if "ck_agents_mode" not in check_names:
            batch.create_check_constraint("ck_agents_mode", "mode IN ('standard', 'managed')")

    inspector = sa.inspect(bind)
    run_columns = _column_names(inspector, "runs")
    run_additions = {
        "target_agent_id": sa.Column(
            "target_agent_id", sa.Integer(),
            sa.ForeignKey("agents.id", name="fk_runs_target_agent_id_agents"), nullable=True,
        ),
        "requested_by": sa.Column(
            "requested_by", sa.Integer(),
            sa.ForeignKey("users.id", name="fk_runs_requested_by_users"), nullable=True,
        ),
        "dispatch_type": sa.Column(
            "dispatch_type", sa.String(length=30), nullable=False, server_default="standard"
        ),
        "schedule_id": sa.Column(
            "schedule_id", sa.Integer(),
            sa.ForeignKey("managed_schedules.id", name="fk_runs_schedule_id_managed_schedules"),
            nullable=True,
        ),
        "scheduled_for": sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        "expires_at": sa.Column("expires_at", sa.DateTime(), nullable=True),
        "claimed_at": sa.Column("claimed_at", sa.DateTime(), nullable=True),
    }
    missing_run_columns = [column for name, column in run_additions.items() if name not in run_columns]
    if missing_run_columns:
        with op.batch_alter_table("runs") as batch:
            for column in missing_run_columns:
                batch.add_column(column)

    inspector = sa.inspect(bind)
    check_names = {item.get("name") for item in inspector.get_check_constraints("runs")}
    if "ck_runs_dispatch_type" not in check_names:
        with op.batch_alter_table("runs") as batch:
            batch.create_check_constraint(
                "ck_runs_dispatch_type",
                "dispatch_type IN ('standard', 'managed_manual', 'managed_schedule')",
            )

    inspector = sa.inspect(bind)
    index_names = _index_names(inspector, "runs")
    if "ix_runs_target_pending" not in index_names:
        op.create_index(
            "ix_runs_target_pending", "runs", ["target_agent_id", "status", "scheduled_for"], unique=False
        )
    if "ix_runs_schedule_status" not in index_names:
        op.create_index("ix_runs_schedule_status", "runs", ["schedule_id", "status"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "runs" in set(inspector.get_table_names()):
        # Directed work must become terminal before target_agent_id is removed;
        # otherwise downgrade would turn it into claimable public work.
        bind.execute(sa.text(
            "UPDATE runs SET status='cancelled', finished_at=CURRENT_TIMESTAMP, "
            "error_msg=COALESCE(error_msg, 'Managed task cancelled during downgrade') "
            "WHERE target_agent_id IS NOT NULL AND status='pending'"
        ))
        bind.execute(sa.text(
            "UPDATE runs SET status='failed', finished_at=CURRENT_TIMESTAMP, "
            "error_msg=COALESCE(error_msg, 'Managed task failed during downgrade') "
            "WHERE target_agent_id IS NOT NULL AND status='running'"
        ))
        index_names = _index_names(inspector, "runs")
        if "ix_runs_target_pending" in index_names:
            op.drop_index("ix_runs_target_pending", table_name="runs")
        if "ix_runs_schedule_status" in index_names:
            op.drop_index("ix_runs_schedule_status", table_name="runs")
        inspector = sa.inspect(bind)
        columns = _column_names(inspector, "runs")
        check_names = {item.get("name") for item in inspector.get_check_constraints("runs")}
        foreign_key_names = {
            item.get("name") for item in inspector.get_foreign_keys("runs") if item.get("name")
        }
        with op.batch_alter_table("runs") as batch:
            if "ck_runs_dispatch_type" in check_names:
                batch.drop_constraint("ck_runs_dispatch_type", type_="check")
            for constraint_name in (
                "fk_runs_target_agent_id_agents", "fk_runs_requested_by_users",
                "fk_runs_schedule_id_managed_schedules",
            ):
                if constraint_name in foreign_key_names:
                    batch.drop_constraint(constraint_name, type_="foreignkey")
            for name in (
                "claimed_at", "expires_at", "scheduled_for", "schedule_id",
                "dispatch_type", "requested_by", "target_agent_id",
            ):
                if name in columns:
                    batch.drop_column(name)

    inspector = sa.inspect(bind)
    if "managed_schedules" in set(inspector.get_table_names()):
        op.drop_table("managed_schedules")

    inspector = sa.inspect(bind)
    if "agents" in set(inspector.get_table_names()):
        columns = _column_names(inspector, "agents")
        check_names = {item.get("name") for item in inspector.get_check_constraints("agents")}
        unique_names = {item.get("name") for item in inspector.get_unique_constraints("agents")}
        with op.batch_alter_table("agents") as batch:
            if "ck_agents_mode" in check_names:
                batch.drop_constraint("ck_agents_mode", type_="check")
            if "uq_agents_device_uid" in unique_names:
                batch.drop_constraint("uq_agents_device_uid", type_="unique")
            for name in ("agent_token_issued_at", "enabled", "mode", "device_uid"):
                if name in columns:
                    batch.drop_column(name)
