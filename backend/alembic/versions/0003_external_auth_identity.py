"""Add optional external authentication identity fields."""

from alembic import op
import sqlalchemy as sa


revision = "0003_external_auth_identity"
down_revision = "0002_adopt_release_090"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "auth_source" not in columns:
            batch.add_column(sa.Column("auth_source", sa.String(length=50), nullable=False, server_default="local"))
        if "external_subject" not in columns:
            batch.add_column(sa.Column("external_subject", sa.String(length=255), nullable=True))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("users")}
    if "uq_user_external_identity" not in indexes:
        op.create_index(
            "uq_user_external_identity",
            "users",
            ["auth_source", "external_subject"],
            unique=True,
        )


def downgrade():
    op.drop_index("uq_user_external_identity", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("external_subject")
        batch.drop_column("auth_source")
