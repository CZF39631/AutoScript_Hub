"""设备授权、固定版本任务及幂等离线历史。兼容 0001 当前 metadata 建库。"""
from alembic import op
import sqlalchemy as sa

revision = "0007_task_scheduling"
down_revision = "0006_diagnostic_policy"
branch_labels = None
depends_on = None

# 冻结迁移结构，未来 ORM 增列不能改变历史 0007 的升级/降级行为。
_metadata = sa.MetaData()
for _name in ('users', 'scripts', 'runs'):
    sa.Table(_name, _metadata, sa.Column('id', sa.Integer, primary_key=True))

_device = sa.Table('task_devices', _metadata,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('device_uuid', sa.String(36), unique=True, nullable=False),
    sa.Column('secret_hash', sa.String(64), nullable=False),
    sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
    sa.Column('name', sa.String(200), nullable=False),
    sa.Column('agent_version', sa.String(40)),
    sa.Column('status', sa.String(20), nullable=False),
    sa.Column('last_heartbeat', sa.DateTime, nullable=False),
    sa.Column('active_execution_id', sa.Integer))
_grant = sa.Table('device_grants', _metadata,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('device_id', sa.Integer, sa.ForeignKey('task_devices.id'), nullable=False),
    sa.Column('requester_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
    sa.Column('script_id', sa.Integer, sa.ForeignKey('scripts.id'), nullable=False),
    sa.Column('script_version', sa.Integer, nullable=False),
    sa.Column('status', sa.String(20), nullable=False),
    sa.UniqueConstraint('device_id', 'requester_id', 'script_id', 'script_version', name='uq_device_grant'))
_task = sa.Table('scheduled_tasks', _metadata,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('name', sa.String(200), nullable=False),
    sa.Column('requester_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
    sa.Column('device_id', sa.Integer, sa.ForeignKey('task_devices.id'), nullable=False),
    sa.Column('script_id', sa.Integer, sa.ForeignKey('scripts.id'), nullable=False),
    sa.Column('script_version', sa.Integer, nullable=False),
    sa.Column('params', sa.Text, nullable=False),
    sa.Column('trigger', sa.Text, nullable=False),
    sa.Column('timeout_seconds', sa.Integer, nullable=False),
    sa.Column('requires_desktop', sa.Boolean, nullable=False),
    sa.Column('requires_browser', sa.Boolean, nullable=False),
    sa.Column('enabled', sa.Boolean, nullable=False),
    sa.Column('is_deleted', sa.Boolean, nullable=False),
    sa.Column('revision', sa.Integer, nullable=False),
    sa.Column('next_fire_at', sa.DateTime))
_execution = sa.Table('task_executions', _metadata,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('task_id', sa.Integer, sa.ForeignKey('scheduled_tasks.id'), nullable=False),
    sa.Column('device_id', sa.Integer, sa.ForeignKey('task_devices.id'), nullable=False),
    sa.Column('run_id', sa.Integer, sa.ForeignKey('runs.id'), unique=True, nullable=False),
    sa.Column('revision', sa.Integer, nullable=False),
    sa.Column('scheduled_for', sa.DateTime),
    sa.Column('request_id', sa.String(36)),
    sa.Column('attempt_id', sa.String(36)),
    sa.Column('state', sa.String(20), nullable=False),
    sa.Column('error_msg', sa.Text),
    sa.Column('claimed_at', sa.DateTime),
    sa.Column('stopped', sa.Boolean, nullable=False),
    sa.UniqueConstraint('task_id', 'revision', 'scheduled_for', name='uq_task_occurrence'),
    sa.UniqueConstraint('task_id', 'request_id', name='uq_task_request'))
_import = sa.Table('local_run_imports', _metadata,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('device_id', sa.Integer, sa.ForeignKey('task_devices.id'), nullable=False),
    sa.Column('request_id', sa.String(36), nullable=False),
    sa.Column('payload_hash', sa.String(64), nullable=False),
    sa.Column('run_id', sa.Integer, sa.ForeignKey('runs.id'), unique=True, nullable=False),
    sa.UniqueConstraint('device_id', 'request_id', name='uq_local_run_import'))
TABLES = (_device, _grant, _task, _execution, _import)
DEFAULTS = {"status": "offline", "state": "queued", "params": "{}", "trigger": '{"kind":"manual"}',
            "timeout_seconds": "600", "requires_desktop": "0", "requires_browser": "0",
            "enabled": "0", "is_deleted": "0", "revision": "1", "stopped": "0"}


def upgrade():
    bind = op.get_bind()
    for table in TABLES:
        if not sa.inspect(bind).has_table(table.name):
            table.create(bind, checkfirst=True)
            continue
        columns = {c["name"] for c in sa.inspect(bind).get_columns(table.name)}
        for column in table.columns:
            if column.name in columns:
                continue
            # 已有开发表仅补安全默认列；缺少身份必填列时失败，不伪造授权。
            default = DEFAULTS.get(column.name)
            op.add_column(table.name, sa.Column(column.name, column.type,
                          nullable=column.nullable,
                          server_default=default))
        inspector = sa.inspect(bind)
        unique = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
        unique.update(tuple(i["column_names"]) for i in inspector.get_indexes(table.name) if i["unique"])
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                names = tuple(c.name for c in constraint.columns)
                if names not in unique:
                    op.create_index(constraint.name or "uq_" + table.name + "_" + "_".join(names),
                                    table.name, list(names), unique=True)


def downgrade():
    for table in reversed(TABLES):
        table.drop(op.get_bind(), checkfirst=True)
