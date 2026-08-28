from collections import defaultdict, deque
from datetime import datetime, timezone
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserBrief
from app.auth import verify_password, create_access_token, get_current_user
from app.services.audit import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_FAILURES = 5
_login_failures = defaultdict(deque)
_login_lock = threading.Lock()


def _login_key(request, username):
    address = request.client.host if request.client else "unknown"
    return (address, username.strip().lower())


def _check_login_limit(key):
    now = time.monotonic()
    with _login_lock:
        failures = _login_failures[key]
        while failures and now - failures[0] >= _LOGIN_WINDOW_SECONDS:
            failures.popleft()
        if len(failures) >= _LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")


def _record_login_failure(key):
    with _login_lock:
        _login_failures[key].append(time.monotonic())


def _clear_login_failures(key):
    with _login_lock:
        _login_failures.pop(key, None)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    login_key = _login_key(request, req.username)
    _check_login_limit(login_key)
    user = db.query(User).filter(User.username == req.username, User.is_deleted == False).first()
    if not user or not verify_password(req.password, user.password_hash):
        _record_login_failure(login_key)
        write_audit(None, req.username, "login_failed", detail="用户名或密码错误",
                    ip_address=request.client.host if request.client else None)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    _clear_login_failures(login_key)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    write_audit(user.id, user.username, "login", ip_address=request.client.host if request.client else None)

    token = create_access_token(user.id, user.role)
    return LoginResponse(token=token, user=UserBrief.model_validate(user))


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    write_audit(current_user.id, current_user.username, "logout")
    return {"message": "已退出登录"}
