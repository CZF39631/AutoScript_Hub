"""Add cron rules and timezone to managed schedules."""

from alembic import op
import sqlalchemy as sa

revision = "0008_managed_schedule_cron"
down_revision = "0007_agent_thumbnails"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("managed_schedules")}
    constraints = {item["name"] for item in inspector.get_check_constraints("managed_schedules")}
    with op.batch_alter_table("managed_schedules") as batch:
        if "schedule_type" not in columns:
            batch.add_column(sa.Column("schedule_type", sa.String(20), nullable=False, server_default="interval"))
        if "cron_expression" not in columns:
            batch.add_column(sa.Column("cron_expression", sa.String(100), nullable=True))
        if "timezone" not in columns:
            batch.add_column(sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"))
        batch.alter_column("interval_seconds", existing_type=sa.Integer(), nullable=True)
        if "ck_managed_schedules_interval" in constraints:
            batch.drop_constraint("ck_managed_schedules_interval", type_="check")
        if "ck_managed_schedules_type" not in constraints:
            batch.create_check_constraint("ck_managed_schedules_type", "schedule_type IN ('interval', 'cron')")
        if "ck_managed_schedules_rule" not in constraints:
            batch.create_check_constraint(
                "ck_managed_schedules_rule",
                "(schedule_type = 'interval' AND interval_seconds >= 60 AND cron_expression IS NULL) "
                "OR (schedule_type = 'cron' AND interval_seconds IS NULL AND cron_expression IS NOT NULL)",
            )


def downgrade():
    # Cron rows cannot be represented by the old schema; fail rather than silently corrupt them.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM managed_schedules WHERE schedule_type = 'cron' LIMIT 1")).first():
        raise RuntimeError("存在 cron 托管计划，无法降级到 0007")
    with op.batch_alter_table("managed_schedules") as batch:
        batch.drop_constraint("ck_managed_schedules_rule", type_="check")
        batch.drop_constraint("ck_managed_schedules_type", type_="check")
        batch.alter_column("interval_seconds", existing_type=sa.Integer(), nullable=False)
        batch.create_check_constraint("ck_managed_schedules_interval", "interval_seconds >= 60")
        batch.drop_column("timezone")
        batch.drop_column("cron_expression")
        batch.drop_column("schedule_type")
