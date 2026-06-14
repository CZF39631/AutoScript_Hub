from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class UserBrief(BaseModel):
    id: int
    username: str
    display_name: str
    role: str

    class Config:
        orm_mode = True


class LoginResponse(BaseModel):
    token: str
    user: UserBrief


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str
    role: str = "operator"


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


class UserDetail(UserBrief):
    status: str
    last_login_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ScriptBrief(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    latest_version: int
    status: str
    created_at: datetime
    installed: Optional[bool] = None

    class Config:
        orm_mode = True


class ScriptDetail(ScriptBrief):
    config_json: Optional[str] = None
    type: str
    updated_at: datetime

    class Config:
        orm_mode = True


class ScriptVersionBrief(BaseModel):
    id: int
    version: int
    changelog: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ExecuteRequest(BaseModel):
    script_id: int
    params: Dict[str, Any] = Field(default_factory=dict)
    environment_id: Optional[int] = None


class RunBrief(BaseModel):
    id: int
    script_id: int
    script_version: int
    user_id: int
    status: str
    params: Optional[str] = None
    result_files: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_sec: Optional[int] = None
    created_at: datetime
    username: Optional[str] = None
    script_name: Optional[str] = None

    class Config:
        orm_mode = True


class RunDetail(RunBrief):
    params: Optional[str] = None
    error_msg: Optional[str] = None
    result_files: Optional[str] = None
    log_path: Optional[str] = None
