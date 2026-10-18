from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db
from app import models
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    get_user_role_codes,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, description="唯一用户名")
    real_name: str = Field(..., min_length=2, max_length=64, description="真实姓名")
    email: EmailStr = Field(..., description="唯一邮箱")
    password: str = Field(..., min_length=8, max_length=64, description="密码至少8位")
    department_id: int = Field(..., description="申请加入的部门ID")


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/departments", summary="获取公开可用部门列表(供注册下拉选择)")
def list_public_departments(db: Session = Depends(get_db)):
    depts = db.query(models.Department).filter(models.Department.is_active == 1).all()
    return [{"id": d.id, "code": d.code, "name": d.name} for d in depts]


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="员工注册")
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    """
    注册新用户：
    - 校验用户名与邮箱唯一，密码 >= 8 位并使用 BCrypt 哈希存储
    - 默认赋予普通员工角色，状态设为 ACTIVE (普通员工立即可用，高权限角色必须由管理员后台授予)
    """
    existing = (
        db.query(models.User)
        .filter((models.User.username == payload.username) | (models.User.email == payload.email))
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已被注册")

    dept = (
        db.query(models.Department)
        .filter(models.Department.id == payload.department_id, models.Department.is_active == 1)
        .first()
    )
    if not dept:
        raise HTTPException(status_code=400, detail="所选部门不存在或已停用")

    new_user = models.User(
        username=payload.username.strip(),
        real_name=payload.real_name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        department_id=dept.id,
        status="ACTIVE",  # 默认普通员工状态，高权限需管理员确认授予
    )
    db.add(new_user)
    db.flush()

    # 默认仅绑定 EMPLOYEE 普通员工角色，严禁客户端自行传入角色
    emp_role = db.query(models.Role).filter_by(code="EMPLOYEE").first()
    if emp_role:
        db.add(models.UserRole(user_id=new_user.id, role_id=emp_role.id))

    db.commit()
    db.refresh(new_user)
    return {
        "message": "注册成功，默认已开通普通员工权限（高权限角色需由系统管理员确认授予）",
        "user_id": new_user.id,
        "username": new_user.username,
    }


@router.post("/login", summary="用户登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.status == "DISABLED":
        raise HTTPException(status_code=403, detail="账号已被管理员停用")

    roles = get_user_role_codes(db, user.id)
    dept = db.query(models.Department).filter(models.Department.id == user.department_id).first()

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "email": user.email,
            "status": user.status,
            "department_id": user.department_id,
            "department_name": dept.name if dept else "",
            "roles": roles,
        },
    }


@router.get("/me", summary="获取当前登录人信息与权限范围")
def get_me(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    roles = get_user_role_codes(db, current_user.id)
    dept = db.query(models.Department).filter(models.Department.id == current_user.department_id).first()
    return {
        "id": current_user.id,
        "username": current_user.username,
        "real_name": current_user.real_name,
        "email": current_user.email,
        "status": current_user.status,
        "department_id": current_user.department_id,
        "department_name": dept.name if dept else "",
        "roles": roles,
    }