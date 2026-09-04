"""Add the persistent global server update settings singleton."""

from alembic import op
import sqlalchemy as sa


revision = "0005_server_settings"
down_revision = "0004_grouped_marketplace"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "server_settings" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "server_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("outbound_proxy", sa.String(length=2048), nullable=True),
            sa.Column(
                "github_repository",
                sa.String(length=255),
                nullable=False,
                server_default="CZF39631/AutoScript_Hub",
            ),
            sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="6"),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.CheckConstraint("id = 1", name="ck_server_settings_singleton"),
            sa.CheckConstraint(
                "interval_hours >= 1 AND interval_hours <= 168",
                name="ck_server_settings_interval",
            ),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(
        sa.text(
            "INSERT INTO server_settings "
            "(id, enabled, outbound_proxy, github_repository, interval_hours, updated_at) "
            "SELECT 1, false, NULL, 'CZF39631/AutoScript_Hub', 6, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM server_settings WHERE id = 1)"
        )
    )


def downgrade():
    if "server_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("server_settings")
