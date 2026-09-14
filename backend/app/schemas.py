from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


from uuid import UUID
from pydantic import field_validator
import json


class TaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceRegister(TaskPayload):
    device_uuid: UUID
    device_secret: str = Field(min_length=32, max_length=256)
    name: str = Field(min_length=1, max_length=200)
    agent_version: str = Field(default="", max_length=40)


class GrantRequest(TaskPayload):
    script_id: int = Field(gt=0, strict=True)
    script_version: int = Field(gt=0, strict=True)


class GrantDecision(TaskPayload):
    decision: Literal["accept", "reject", "revoke"]


class TaskCreate(GrantRequest):
    name: str = Field(min_length=1, max_length=200)
    device_id: int = Field(gt=0, strict=True)
    params: Dict[str, Any] = Field(default_factory=dict)
    trigger: Dict[str, Any]
    timeout_seconds: int = Field(default=600, ge=1, le=86400, strict=True)
    requires_desktop: bool = Field(default=False, strict=True)
    requires_browser: bool = Field(default=False, strict=True)

    @field_validator("params", "trigger")
    @classmethod
    def bounded_json(cls, value):
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 65536:
            raise ValueError("JSON 不得超过 64 KiB")
        return value


class TaskAction(TaskPayload):
    action: Literal["run", "pause", "resume", "delete"]
    request_id: Optional[UUID] = None


class TaskAttempt(TaskPayload):
    attempt_id: UUID


class TaskReport(TaskAttempt):
    state: Literal["success", "failed", "cancelled", "unknown"]
    stopped: Literal[True]

    @field_validator("stopped", mode="before")
    @classmethod
    def confirmed_stop(cls, value):
        if value is not True:
            raise ValueError("必须明确确认 stopped: true")
        return value

    error_msg: Optional[str] = Field(default=None, max_length=4096)
    result_files: Optional[List[str]] = Field(default=None, max_length=100)
    log_tail: Optional[str] = Field(default=None, max_length=65536)

    @field_validator("log_tail", "result_files", "error_msg")
    @classmethod
    def bounded_output(cls, value, info):
        encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        limit = 4096 if info.field_name == "error_msg" else 65536
        if value is not None and len(encoded.encode("utf-8")) > limit:
            raise ValueError("输出超过 UTF-8 字节上限")
        return value


class LocalRunImportRequest(TaskPayload):
    device_id: int = Field(gt=0, strict=True)
    request_id: UUID
    script_id: int = Field(gt=0, strict=True)
    script_version: int = Field(gt=0, strict=True)
    status: Literal["success", "failed", "cancelled"]
    params: Dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime
    error_msg: Optional[str] = Field(default=None, max_length=4096)
    result_files: Optional[List[str]] = Field(default=None, max_length=100)
    log_tail: Optional[str] = Field(default=None, max_length=65536)

    @field_validator("log_tail", "result_files", "error_msg", "params")
    @classmethod
    def bounded_output(cls, value, info):
        encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
        limit = 4096 if info.field_name == "error_msg" else 65536
        if value is not None and len(encoded.encode("utf-8")) > limit:
            raise ValueError("输出超过 UTF-8 字节上限")
        return value

    @field_validator("started_at", "finished_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("时间须包含时区")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserBrief


UserRole = Literal["admin", "developer", "operator"]
UserStatus = Literal["active", "disabled"]
GroupStatus = Literal["active", "disabled"]


class GroupBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    status: str
    is_default: bool


class GroupDetail(GroupBrief):
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    script_count: int = 0


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: GroupStatus = "active"
    is_default: bool = False


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[GroupStatus] = None
    is_default: Optional[bool] = None


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=4, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)
    role: UserRole = "operator"
    group_ids: Optional[List[int]] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None
    group_ids: Optional[List[int]] = None


class UserDetail(UserBrief):
    status: str
    auth_source: str
    last_login_at: Optional[datetime] = None
    created_at: datetime
    groups: List[GroupBrief] = Field(default_factory=list)


class ScriptBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    latest_version: int
    latest_semantic_version: Optional[str] = None
    status: str
    created_at: datetime
    installed: Optional[bool] = None
    groups: List[GroupBrief] = Field(default_factory=list)
    can_manage: bool = False
    can_manage_groups: bool = False


class ScriptDetail(ScriptBrief):
    config_json: Optional[str] = None
    type: str
    updated_at: datetime


class ScriptGroupUpdate(BaseModel):
    group_ids: List[int] = Field(default_factory=list)


class ScriptVersionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    semantic_version: Optional[str] = None
    changelog: Optional[str] = None
    created_at: datetime


class ExecuteRequest(BaseModel):
    script_id: int
    params: Dict[str, Any] = Field(default_factory=dict)
    environment_id: Optional[int] = None


class RunBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    script_id: int
    script_version: int
    script_semantic_version: Optional[str] = None
    user_id: int
    agent_id: Optional[int] = None
    task_execution_id: Optional[int] = None
    status: str
    params: Optional[str] = None
    result_files: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_sec: Optional[int] = None
    created_at: datetime
    username: Optional[str] = None
    script_name: Optional[str] = None


class RunDetail(RunBrief):
    params: Optional[str] = None
    error_msg: Optional[str] = None
    result_files: Optional[str] = None
    log_path: Optional[str] = None
