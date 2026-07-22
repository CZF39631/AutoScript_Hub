from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base  # type: ignore[attr-defined]

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
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


class Agent(Base):
    """Remote client machine registration (design §4.4).

    Tracks machine identity + online status from the server's perspective.
    Coexists with Environment: Agent = "which machine", Environment = "how to run on it".
    """
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    machine_name = Column(String(200), nullable=False)
    machine_ip = Column(String(50), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="offline")  # online / offline
    agent_version = Column(String(20), nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)


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


class Run(Base):
    __tablename__ = "runs"

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
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    log_path = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    script = relationship("Script", back_populates="runs")  # type: ignore[call-arg]
    user = relationship("User", back_populates="runs", foreign_keys=[user_id])  # type: ignore[call-arg]


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
