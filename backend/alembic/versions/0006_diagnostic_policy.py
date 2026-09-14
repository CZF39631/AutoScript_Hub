"""Persist the administrator-controlled diagnostic redaction policy."""

from alembic import op
import sqlalchemy as sa

revision = "0006_diagnostic_policy"
down_revision = "0005_server_settings"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("server_settings")}
    # 0001 在新安装时使用当前 metadata，因此需要兼容列已存在的情况。
    if "diagnostic_policy_json" not in columns:
        op.add_column("server_settings", sa.Column(
            "diagnostic_policy_json", sa.Text(), nullable=False, server_default="{}",
        ))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("server_settings")}
    if "diagnostic_policy_json" in columns:
        with op.batch_alter_table("server_settings") as batch:
            batch.drop_column("diagnostic_policy_json")
