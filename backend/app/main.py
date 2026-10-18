from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app import models

app = FastAPI(
    title="企业智能协同审批系统 API",
    description="ZJU B/S体系软件设计课程项目后端接口",
    version="1.0.0"
)

# 允许前端跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """检查后端服务及数据库连接状态"""
    result = db.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'approval_system'"))
    table_count = result.scalar()
    return {
        "status": "ok",
        "database": "connected",
        "tables_count": table_count,
        "loaded_models": len(models.Base.metadata.tables)
    }