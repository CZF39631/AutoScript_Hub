from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES
from app.database import get_db
from app.models import Agent, User

# auto_error=False so we can return 401 (not the default 403) when no token is provided.
# Per HTTP semantics: 401 = "not authenticated" (no/invalid creds), 403 = "authenticated but forbidden".
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "kind": "user", "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_agent_token(agent_id: int, user_id: int) -> str:
    """Issue a long-lived, server-signed credential bound to one Agent."""
    expire = datetime.now(timezone.utc) + timedelta(days=180)
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "agent_id": agent_id,
        "kind": "agent",
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_agent_token(token: Optional[str], agent: Agent, *, allow_expired: bool = False) -> None:
    """Require a valid device credential for a managed Agent."""
    if agent.mode != "managed":
        return
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 Agent 设备令牌")
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": not allow_expired},
        )
        token_agent_id = int(payload.get("agent_id"))
        token_user_id = int(payload.get("user_id"))
    except (InvalidTokenError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 Agent 设备令牌")
    if (
        payload.get("kind") != "agent"
        or token_agent_id != agent.id
        or token_user_id != agent.user_id
        or str(payload.get("sub")) != str(agent.user_id)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent 设备令牌与目标不匹配")


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
):
    # No credentials provided at all → 401 (not 403, which would imply "authenticated but forbidden")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("kind") == "agent":
            raise InvalidTokenError("agent token cannot authenticate a user session")
        user_id = int(payload.get("sub"))
    except (InvalidTokenError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的令牌")
    user = db.query(User).filter(
        User.id == user_id, User.status == "active", User.is_deleted == False
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def require_role(*roles: str):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return current_user
    return checker
