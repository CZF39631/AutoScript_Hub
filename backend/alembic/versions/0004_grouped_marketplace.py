"""Add user groups and group-scoped script marketplace."""

from alembic import op
import sqlalchemy as sa


revision = "0004_grouped_marketplace"
down_revision = "0003_external_auth_identity"
branch_labels = None
depends_on = None


DEFAULT_GROUP_NAME = "默认分组"


def upgrade():
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "groups" not in existing_tables:
        op.create_table(
            "groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_groups_name"),
        )
        op.create_index("ix_groups_id", "groups", ["id"], unique=False)

    if "user_groups" not in existing_tables:
        op.create_table(
            "user_groups",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("user_id", "group_id"),
        )
        op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"], unique=False)

    if "script_groups" not in existing_tables:
        op.create_table(
            "script_groups",
            sa.Column("script_id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
            sa.ForeignKeyConstraint(["script_id"], ["scripts.id"]),
            sa.PrimaryKeyConstraint("script_id", "group_id"),
        )
        op.create_index("ix_script_groups_group_id", "script_groups", ["group_id"], unique=False)

    default_group_id = bind.execute(
        sa.text(
            "SELECT id FROM groups "
            "WHERE is_default = true AND status = 'active' AND is_deleted = false ORDER BY id"
        )
    ).scalar()
    if default_group_id is None:
        default_group_id = bind.execute(
            sa.text("SELECT id FROM groups WHERE name = :name"),
            {"name": DEFAULT_GROUP_NAME},
        ).scalar()
        if default_group_id is None:
            bind.execute(
                sa.text(
                    "INSERT INTO groups "
                    "(name, description, status, is_default, created_at, updated_at, is_deleted) "
                    "VALUES (:name, :description, 'active', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, false)"
                ),
                {"name": DEFAULT_GROUP_NAME, "description": "升级时自动创建，用于保持原有市场可见范围"},
            )
            default_group_id = bind.execute(
                sa.text("SELECT id FROM groups WHERE name = :name"),
                {"name": DEFAULT_GROUP_NAME},
            ).scalar_one()
        else:
            bind.execute(
                sa.text(
                    "UPDATE groups SET status='active', is_default=true, is_deleted=false, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=:group_id"
                ),
                {"group_id": default_group_id},
            )
    bind.execute(
        sa.text("UPDATE groups SET is_default=false WHERE id != :group_id AND is_default=true"),
        {"group_id": default_group_id},
    )
    index_names = {item["name"] for item in sa.inspect(bind).get_indexes("groups")}
    if "uq_groups_single_default" not in index_names and bind.dialect.name in {"sqlite", "postgresql"}:
        where_options = (
            {"sqlite_where": sa.text("is_default = 1 AND is_deleted = 0")}
            if bind.dialect.name == "sqlite"
            else {"postgresql_where": sa.text("is_default = true AND is_deleted = false")}
        )
        op.create_index(
            "uq_groups_single_default",
            "groups",
            ["is_default"],
            unique=True,
            **where_options,
        )
    bind.execute(
        sa.text(
            "INSERT INTO user_groups (user_id, group_id, created_at) "
            "SELECT users.id, :group_id, CURRENT_TIMESTAMP FROM users "
            "WHERE NOT EXISTS (SELECT 1 FROM user_groups WHERE user_groups.user_id = users.id)"
        ),
        {"group_id": default_group_id},
    )
    bind.execute(
        sa.text(
            "INSERT INTO script_groups (script_id, group_id, created_at) "
            "SELECT scripts.id, :group_id, CURRENT_TIMESTAMP FROM scripts "
            "WHERE NOT EXISTS (SELECT 1 FROM script_groups WHERE script_groups.script_id = scripts.id)"
        ),
        {"group_id": default_group_id},
    )


def downgrade():
    bind = op.get_bind()
    index_names = {item["name"] for item in sa.inspect(bind).get_indexes("groups")}
    if "uq_groups_single_default" in index_names:
        op.drop_index("uq_groups_single_default", table_name="groups")
    op.drop_index("ix_script_groups_group_id", table_name="script_groups")
    op.drop_table("script_groups")
    op.drop_index("ix_user_groups_group_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_index("ix_groups_id", table_name="groups")
    op.drop_table("groups")
