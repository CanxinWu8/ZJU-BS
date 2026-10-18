from datetime import datetime, timedelta, timezone
from typing import Optional, List
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    """使用 bcrypt 对密码进行哈希存储（不保存明文密码）"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否一致"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """签发 JWT Access Token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def get_user_role_codes(db: Session, user_id: int) -> List[str]:
    """查询用户当前拥有的全部角色编码列表"""
    rows = (
        db.query(models.Role.code)
        .join(models.UserRole, models.UserRole.role_id == models.Role.id)
        .filter(models.UserRole.user_id == user_id)
        .all()
    )
    return [r[0] for r in rows]


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> models.User:
    """服务端强制鉴权依赖：解析 JWT 并返回当前有效用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或登录凭证已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise credentials_exception
    if user.status == "DISABLED":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该账号已被停用")
    return user


def require_roles(*allowed_roles: str):
    """服务端角色权限检查装饰器依赖：仅允许具备指定角色的用户访问"""
    def role_checker(
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> models.User:
        if current_user.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账号尚处于待管理员确认状态，暂无法执行此操作"
            )
        user_roles = get_user_role_codes(db, current_user.id)
        if not any(role in user_roles for role in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足：需要角色 {allowed_roles}，当前拥有 {user_roles}"
            )
        return current_user

    return role_checker