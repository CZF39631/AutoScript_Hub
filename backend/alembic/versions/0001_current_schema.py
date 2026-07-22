"""Create the complete AutoScript Hub schema for fresh databases."""

from alembic import op

from app.models import Base
from app.routers.settings import UserSettings  # noqa: F401 - registers metadata


revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
