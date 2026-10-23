"""Record the source Run for managed retries."""

from alembic import op
import sqlalchemy as sa


revision = "0009_run_retry_lineage"
down_revision = "0008_managed_schedule_cron"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("runs")}
    if "retry_of_run_id" not in columns:
        with op.batch_alter_table("runs") as batch:
            batch.add_column(sa.Column("retry_of_run_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_runs_retry_of_run_id_runs", "runs", ["retry_of_run_id"], ["id"]
            )

    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("runs")}
    if "ix_runs_retry_of_run_id" not in indexes:
        op.create_index("ix_runs_retry_of_run_id", "runs", ["retry_of_run_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("runs")}
    columns = {item["name"] for item in inspector.get_columns("runs")}
    if "ix_runs_retry_of_run_id" in indexes:
        op.drop_index("ix_runs_retry_of_run_id", table_name="runs")
    if "retry_of_run_id" in columns:
        foreign_keys = {
            item.get("name") for item in inspector.get_foreign_keys("runs") if item.get("name")
        }
        with op.batch_alter_table("runs") as batch:
            if "fk_runs_retry_of_run_id_runs" in foreign_keys:
                batch.drop_constraint("fk_runs_retry_of_run_id_runs", type_="foreignkey")
            batch.drop_column("retry_of_run_id")
