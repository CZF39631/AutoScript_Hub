from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserBrief
from app.auth import verify_password, create_access_token, get_current_user
from app.services.audit import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username, User.is_deleted == False).first()
    if not user or not verify_password(req.password, user.password_hash):
        write_audit(None, req.username, "login_failed", detail="用户名或密码错误",
                    ip_address=request.client.host if request.client else None)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    write_audit(user.id, user.username, "login", ip_address=request.client.host if request.client else None)

    token = create_access_token(user.id, user.role)
    return LoginResponse(token=token, user=UserBrief.from_orm(user))


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    write_audit(current_user.id, current_user.username, "logout")
    return {"message": "已退出登录"}
