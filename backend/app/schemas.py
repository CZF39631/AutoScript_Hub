from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


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


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=4, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)
    role: UserRole = "operator"


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None


class UserDetail(UserBrief):
    status: str
    auth_source: str
    last_login_at: Optional[datetime] = None
    created_at: datetime


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


class ScriptDetail(ScriptBrief):
    config_json: Optional[str] = None
    type: str
    updated_at: datetime


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
