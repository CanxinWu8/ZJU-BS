from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db, SessionLocal
from app import models
from app.seed import run_seed
from app.routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动幂等执行种子数据初始化
    with SessionLocal() as db:
        run_seed(db)
    yield


app = FastAPI(
    title="企业智能协同审批系统 API",
    description="ZJU B/S体系软件设计课程项目后端接口",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)


@app.get("/api/v1/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """检查后端服务及数据库连接状态"""
    result = db.execute(
        text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'approval_system'")
    )
    table_count = result.scalar()
    user_count = db.query(models.User).count()
    return {
        "status": "ok",
        "database": "connected",
        "tables_count": table_count,
        "seeded_users_count": user_count,
    }