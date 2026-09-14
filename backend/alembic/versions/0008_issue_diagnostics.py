"""持久工单诊断快照。"""
from alembic import op
import sqlalchemy as sa

revision = "0008_issue_diagnostics"
down_revision = "0007_task_scheduling"
branch_labels = None
depends_on = None


def upgrade():
    if 'issue_diagnostics' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            'issue_diagnostics',
            sa.Column('issue_id', sa.Integer(), sa.ForeignKey('issues.id'), primary_key=True),
            sa.Column('state', sa.String(32), nullable=False, server_default='collected'),
            sa.Column('payload_json', sa.Text(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index('ix_issue_diagnostics_expires_at', 'issue_diagnostics', ['expires_at'])


def downgrade():
    if "issue_diagnostics" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("issue_diagnostics")
