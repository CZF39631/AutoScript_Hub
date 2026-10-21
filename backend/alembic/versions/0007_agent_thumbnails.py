"""Add managed Agent thumbnail metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0007_agent_thumbnails"
down_revision = "0006_managed_agent_mode"
branch_labels = None
depends_on = None


def _column_names(inspector):
    return {item["name"] for item in inspector.get_columns("agents")}


def upgrade():
    bind = op.get_bind()
    columns = _column_names(sa.inspect(bind))
    additions = []
    if "thumbnail_updated_at" not in columns:
        additions.append(sa.Column("thumbnail_updated_at", sa.DateTime(), nullable=True))
    if "thumbnail_size" not in columns:
        additions.append(sa.Column("thumbnail_size", sa.Integer(), nullable=True))
    if additions:
        with op.batch_alter_table("agents") as batch:
            for column in additions:
                batch.add_column(column)


def downgrade():
    bind = op.get_bind()
    columns = _column_names(sa.inspect(bind))
    with op.batch_alter_table("agents") as batch:
        for name in ("thumbnail_size", "thumbnail_updated_at"):
            if name in columns:
                batch.drop_column(name)
