import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, Table, Index, CheckConstraint
from sqlalchemy.orm import relationship, declarative_base  # type: ignore[attr-defined]

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True),
    Column("created_at", DateTime, nullable=False, default=_utcnow),
    Index("ix_user_groups_group_id", "group_id"),
)

script_groups = Table(
    "script_groups",
    Base.metadata,
    Column("script_id", Integer, ForeignKey("scripts.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True),
    Column("created_at", DateTime, nullable=False, default=_utcnow),
    Index("ix_script_groups_group_id", "group_id"),
)

managed_agent_group_members = Table(
    "managed_agent_group_members",
    Base.metadata,
    Column("agent_id", Integer, ForeignKey("agents.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("managed_agent_groups.id"), primary_key=True),
    Column("created_at", DateTime, nullable=False, default=_utcnow),
    Column("created_by", Integer, ForeignKey("users.id"), nullable=True),
    Index("ix_managed_agent_group_members_group_id", "group_id"),
)


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)

    users = relationship("User", secondary=user_groups, back_populates="groups")  # type: ignore[call-arg]
    scripts = relationship("Script", secondary=script_groups, back_populates="groups")  # type: ignore[call-arg]


def _semantic_version(config_json):
    """Return a script contract SemVer from persisted config JSON when available."""
    if not config_json:
        return None
    try:
        version = json.loads(config_json).get("version")
    except (TypeError, json.JSONDecodeError):
        return None
    return version if isinstance(version, str) and version.strip() else None


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("auth_source", "external_subject", name="uq_user_external_identity"),)

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    auth_source = Column(String(50), nullable=False, default="local")
    external_subject = Column(String(255), nullable=True)
    display_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="operator")
    status = Column(String(20), nullable=False, default="active")
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)

    runs = relationship("Run", back_populates="user", foreign_keys="Run.user_id")  # type: ignore[call-arg]
    groups = relationship("Group", secondary=user_groups, back_populates="users")  # type: ignore[call-arg]


class Agent(Base):
    """Remote client machine registration (design §4.4).

    Tracks machine identity + online status from the server's perspective.
    Coexists with Environment: Agent = "which machine", Environment = "how to run on it".
    """
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("device_uid", name="uq_agents_device_uid"),
        CheckConstraint("mode IN ('standard', 'managed')", name="ck_agents_mode"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_uid = Column(String(255), nullable=False, default=lambda: str(uuid.uuid4()))
    machine_name = Column(String(200), nullable=False)
    machine_ip = Column(String(50), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    mode = Column(String(20), nullable=False, default="standard")
    enabled = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default="offline")  # online / offline
    agent_version = Column(String(20), nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)
    agent_token_issued_at = Column(DateTime, nullable=True)
    thumbnail_updated_at = Column(DateTime, nullable=True)
    thumbnail_size = Column(Integer, nullable=True)
    thumbnail_capture_paused = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    managed_groups = relationship(
        "ManagedAgentGroup", secondary=managed_agent_group_members,
        back_populates="agents",
    )  # type: ignore[call-arg]


class ManagedAgentGroup(Base):
    __tablename__ = "managed_agent_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    agents = relationship(
        "Agent", secondary=managed_agent_group_members,
        back_populates="managed_groups",
    )  # type: ignore[call-arg]


class ManagedAgentBatch(Base):
    __tablename__ = "managed_agent_batches"
    __table_args__ = (
        UniqueConstraint("created_by", "idempotency_key", name="uq_managed_agent_batch_actor_key"),
        Index("ix_managed_agent_batches_actor_created", "created_by", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    operation = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="processing")
    selection_json = Column(Text, nullable=False)
    request_json = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    total_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    items = relationship(
        "ManagedAgentBatchItem", back_populates="batch", order_by="ManagedAgentBatchItem.id"
    )  # type: ignore[call-arg]


class ManagedAgentBatchItem(Base):
    __tablename__ = "managed_agent_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "agent_id", name="uq_managed_agent_batch_item"),
        Index("ix_managed_agent_batch_items_batch_result", "batch_id", "result"),
    )

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("managed_agent_batches.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    result = Column(String(20), nullable=False)
    reason = Column(Text, nullable=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)
    detail_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    batch = relationship("ManagedAgentBatch", back_populates="items")  # type: ignore[call-arg]


class Script(Base):
    __tablename__ = "scripts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    type = Column(String(10), nullable=False, default="py")
    latest_version = Column(Integer, nullable=False, default=0)
    config_json = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)

    versions = relationship("ScriptVersion", back_populates="script", order_by="ScriptVersion.version.desc()")  # type: ignore[call-arg]
    runs = relationship("Run", back_populates="script")  # type: ignore[call-arg]
    groups = relationship("Group", secondary=script_groups, back_populates="scripts")  # type: ignore[call-arg]

    @property
    def latest_semantic_version(self):
        """Display version from config while latest_version remains a storage revision."""
        return _semantic_version(self.config_json)


class ScriptVersion(Base):
    __tablename__ = "script_versions"

    id = Column(Integer, primary_key=True, index=True)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    version = Column(Integer, nullable=False)
    changelog = Column(Text, nullable=True)
    file_path = Column(Text, nullable=False)
    config_json = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    script = relationship("Script", back_populates="versions")  # type: ignore[call-arg]

    @property
    def semantic_version(self):
        """Display SemVer from the immutable version config."""
        return _semantic_version(self.config_json)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "dispatch_type IN ('standard', 'managed_manual', 'managed_schedule')",
            name="ck_runs_dispatch_type",
        ),
        Index("ix_runs_target_pending", "target_agent_id", "status", "scheduled_for"),
        Index("ix_runs_schedule_status", "schedule_id", "status"),
        Index("ix_runs_retry_of_run_id", "retry_of_run_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    script_version = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    params = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)
    result_files = Column(Text, nullable=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # §4.5: which machine executed
    target_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    dispatch_type = Column(String(30), nullable=False, default="standard")
    schedule_id = Column(Integer, ForeignKey("managed_schedules.id"), nullable=True)
    retry_of_run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)
    scheduled_for = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    log_path = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    script = relationship("Script", back_populates="runs")  # type: ignore[call-arg]
    user = relationship("User", back_populates="runs", foreign_keys=[user_id])  # type: ignore[call-arg]


class ManagedSchedule(Base):
    """Admin-defined interval or cron dispatch plan for one managed Agent."""

    __tablename__ = "managed_schedules"
    __table_args__ = (
        CheckConstraint("schedule_type IN ('interval', 'cron')", name="ck_managed_schedules_type"),
        CheckConstraint(
            "(schedule_type = 'interval' AND interval_seconds >= 60 AND cron_expression IS NULL) "
            "OR (schedule_type = 'cron' AND interval_seconds IS NULL AND cron_expression IS NOT NULL)",
            name="ck_managed_schedules_rule",
        ),
        CheckConstraint(
            "expires_after_seconds >= 60",
            name="ck_managed_schedules_expiry",
        ),
        Index("ix_managed_schedules_due", "enabled", "next_run_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    params = Column(Text, nullable=False, default="{}")
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=True)
    schedule_type = Column(String(20), nullable=False, default="interval")
    interval_seconds = Column(Integer, nullable=True)
    cron_expression = Column(String(100), nullable=True)
    timezone = Column(String(100), nullable=False, default="UTC")
    expires_after_seconds = Column(Integer, nullable=False, default=3600)
    enabled = Column(Boolean, nullable=False, default=True)
    next_run_at = Column(DateTime, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    last_missed_at = Column(DateTime, nullable=True)
    last_missed_reason = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)


class UserScript(Base):
    __tablename__ = "user_scripts"
    __table_args__ = (UniqueConstraint("user_id", "script_id", name="uq_user_script"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    installed_at = Column(DateTime, nullable=False, default=_utcnow)


class Environment(Base):
    __tablename__ = "environments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    browser_port = Column(Integer, nullable=True)
    browser_path = Column(String(500), nullable=True)
    python_version = Column(String(20), nullable=True)
    venv_path = Column(String(500), nullable=True)
    venv_status = Column(String(20), nullable=False, default="none")
    python_executable = Column(String(500), nullable=True)
    output_dir = Column(String(500), nullable=True)
    proxy = Column(String(200), nullable=True)
    extra_env = Column(Text, nullable=True)  # JSON: {"KEY": "value", ...}
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(50), nullable=True)
    action = Column(String(50), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=True)
    script_version = Column(Integer, nullable=True)  # §4.6: version at report time
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # §4.6 reporter_id
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    log_snapshot = Column(Text, nullable=True)  # §4.6: log captured at report time
    status = Column(String(20), nullable=False, default="open")
    resolve_note = Column(Text, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_version = Column(Integer, nullable=True)  # §4.6: version that fixed it
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)


class UserPreset(Base):
    """Per-user personal parameter presets for a script (design §5.3).

    Developer presets live inside the script's config_json under the "presets" key
    (read-only for operators); this table stores only an operator's own saved presets.
    """
    __tablename__ = "user_presets"
    __table_args__ = (UniqueConstraint("user_id", "script_id", "name", name="uq_user_preset"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    name = Column(String(100), nullable=False)
    values_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    settings_json = Column(Text, nullable=False, default="{}")


class ServerSettings(Base):
    """Persisted process-wide settings.  The database permits only row id=1."""

    __tablename__ = "server_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_server_settings_singleton"),
        CheckConstraint("interval_hours >= 1 AND interval_hours <= 168", name="ck_server_settings_interval"),
    )

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    outbound_proxy = Column(String(2048), nullable=True)
    github_repository = Column(String(255), nullable=False, default="CZF39631/AutoScript_Hub")
    interval_hours = Column(Integer, nullable=False, default=6)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
