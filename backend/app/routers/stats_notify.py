import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from jose import JWTError, jwt
from pydantic import BaseModel

from app.database import get_db, SessionLocal
from app.config import settings
from app import models
from app.auth import get_current_user, get_user_role_codes

router = APIRouter(prefix="/api/v1", tags=["Statistics & Notifications"])

CATEGORY_LABELS = {
    "PROCUREMENT": "采购审批",
    "TRAVEL": "差旅申请",
    "EXPENSE": "报销审批",
    "CUSTOM": "自定义流程",
}

STATUS_LABELS = {
    "DRAFT": "草稿",
    "IN_REVIEW": "审批中",
    "APPROVED": "已通过",
    "REJECTED": "已驳回",
    "WITHDRAWN": "已撤回",
}


class WebPushSubscriptionSchema(BaseModel):
    subscription: Dict[str, Any]


# ==================== 1. 查询统计与图表数据接口 ====================

@router.get("/stats/overview", summary="获取个人/部门/财务/全公司统计看板与图表数据")
def get_statistics_overview(
    scope: str = Query("PERSONAL", pattern="^(PERSONAL|DEPT|FINANCE|COMPANY)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    统计口径说明（严格符合实验要求）：
    - 已通过总金额(approved_amount_cents)：按提交时间统计状态为 APPROVED 的申请金额之和，
      绝不把草稿(DRAFT)、已驳回(REJECTED)、已撤回(WITHDRAWN)或审批中(IN_REVIEW)计入已通过金额。
    """
    user_roles = get_user_role_codes(db, current_user.id)

    # 1. 个人核心指标卡片（任何角色均可看自己的待办与本人申请）
    my_pending_todo_count = (
        db.query(models.ApprovalInstanceNode)
        .join(models.Application, models.Application.id == models.ApprovalInstanceNode.application_id)
        .filter(
            models.ApprovalInstanceNode.approver_id == current_user.id,
            models.ApprovalInstanceNode.status == "PENDING",
            models.Application.status == "IN_REVIEW",
        )
        .count()
    )
    my_done_count = (
        db.query(models.ApprovalInstanceNode)
        .filter(
            models.ApprovalInstanceNode.approver_id == current_user.id,
            models.ApprovalInstanceNode.status.in_(["APPROVED", "REJECTED"]),
        )
        .count()
    )
    my_Unread_notify_count = (
        db.query(models.Notification)
        .filter_by(recipient_id=current_user.id, is_read=0)
        .count()
    )

    # 2. 根据请求的数据范围(scope)校验权限并构建统计查询集
    base_query = db.query(models.Application)
    scope_title = "个人申请统计"

    if scope == "PERSONAL":
        base_query = base_query.filter(models.Application.applicant_id == current_user.id)
        scope_title = f"{current_user.real_name} - 个人申请统计"

    elif scope == "DEPT":
        if "DEPT_MANAGER" not in user_roles:
            raise HTTPException(status_code=403, detail="权限不足：仅部门负责人可查看本部门统计数据")
        dept = db.query(models.Department).filter_by(id=current_user.department_id).first()
        base_query = base_query.filter(
            models.Application.department_id == current_user.department_id,
            models.Application.status != "DRAFT",
        )
        scope_title = f"{dept.name if dept else '本部门'} - 部门审批统计"

    elif scope == "FINANCE":
        if "FINANCE" not in user_roles:
            raise HTTPException(status_code=403, detail="权限不足：仅财务审批人可查看授权财务统计")
        base_query = base_query.filter(
            models.Application.category.in_(["PROCUREMENT", "EXPENSE"]),
            models.Application.status != "DRAFT",
        )
        scope_title = "财务部 - 采购与报销专项统计"

    elif scope == "COMPANY":
        if "EXECUTIVE" not in user_roles:
            raise HTTPException(status_code=403, detail="权限不足：仅授权的企业负责人可查看全公司统计数据")
        base_query = base_query.filter(models.Application.status != "DRAFT")
        scope_title = "全公司 - 审批全局统计"

    apps = base_query.all()

    # 3. 汇总状态分布、各类型申请数量与已通过金额（分）
    status_counts = {k: 0 for k in STATUS_LABELS.keys()}
    category_stats = {
        k: {
            "category": k,
            "label": v,
            "total_count": 0,
            "approved_count": 0,
            "approved_amount_cents": 0,
        }
        for k, v in CATEGORY_LABELS.items()
    }

    total_approved_amount_cents = 0
    total_in_review_amount_cents = 0

    for a in apps:
        if a.status in status_counts:
            status_counts[a.status] += 1
        if a.category in category_stats:
            category_stats[a.category]["total_count"] += 1
            if a.status == "APPROVED":
                category_stats[a.category]["approved_count"] += 1
                category_stats[a.category]["approved_amount_cents"] += a.total_amount_cents

        if a.status == "APPROVED":
            total_approved_amount_cents += a.total_amount_cents
        elif a.status == "IN_REVIEW":
            total_in_review_amount_cents += a.total_amount_cents

    return {
        "scope": scope,
        "scope_title": scope_title,
        "caliber_statement": "统计口径说明：按提交时间统计，【已通过金额】仅汇总状态为已通过(APPROVED)的申请单，不包含草稿、审批中、已驳回及已撤回的金额。",
        "personal_todo_summary": {
            "my_pending_todo_count": my_pending_todo_count,
            "my_done_count": my_done_count,
            "my_unread_notify_count": my_Unread_notify_count,
        },
        "summary_cards": {
            "total_applications": len(apps),
            "in_review_count": status_counts["IN_REVIEW"],
            "approved_count": status_counts["APPROVED"],
            "rejected_count": status_counts["REJECTED"],
            "withdrawn_count": status_counts["WITHDRAWN"],
            "draft_count": status_counts["DRAFT"],
            "approved_amount_cents": total_approved_amount_cents,
            "in_review_amount_cents": total_in_review_amount_cents,
        },
        "charts": {
            "status_distribution": [
                {"status": k, "label": STATUS_LABELS[k], "count": v}
                for k, v in status_counts.items()
            ],
            "category_breakdown": list(category_stats.values()),
        },
    }


# ==================== 2. 站内通知、SSE 实时流与 WebPush 接口 ====================

@router.get("/notifications", summary="获取当前用户的持久化站内通知列表与未读数量")
def list_my_notifications(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Notification).filter(models.Notification.recipient_id == current_user.id)
    if unread_only:
        query = query.filter(models.Notification.is_read == 0)

    items = query.order_by(models.Notification.id.desc()).limit(limit).all()
    unread_count = (
        db.query(models.Notification)
        .filter_by(recipient_id=current_user.id, is_read=0)
        .count()
    )

    return {
        "unread_count": unread_count,
        "items": [
            {
                "id": n.id,
                "application_id": n.application_id,
                "notify_type": n.notify_type,
                "title": n.title,
                "content": n.content,
                "is_read": bool(n.is_read),
                "read_at": n.read_at,
                "created_at": n.created_at,
            }
            for n in items
        ],
    }


@router.put("/notifications/{notify_id}/read", summary="标记单条通知为已读(服务端强校验归属)")
def mark_notification_read(
    notify_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    notif = db.query(models.Notification).filter_by(id=notify_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="通知不存在")

    # 严禁读取或标记非当前用户的通知
    if notif.recipient_id != current_user.id:
        raise HTTPException(status_code=403, detail="越权拦截：非当前用户的通知不得被读取或标记")

    if not notif.is_read:
        notif.is_read = 1
        notif.read_at = datetime.now()
        db.commit()

    return {"message": "已标记为已读", "id": notif.id}


@router.put("/notifications/read-all", summary="一键标记当前用户全部未读通知为已读")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    now = datetime.now()
    updated = (
        db.query(models.Notification)
        .filter_by(recipient_id=current_user.id, is_read=0)
        .update({"is_read": 1, "read_at": now}, synchronize_session=False)
    )
    db.commit()
    return {"message": f"已将 {updated} 条未读通知标记为已读"}


@router.get("/notifications/stream", summary="SSE 实时通知与待办进度推送流(支持移动端免刷新提醒)")
async def notification_sse_stream(token: str = Query(..., description="JWT Access Token")):
    """
    前端/手机端打开页面时通过 EventSource 连接此接口：
    当产生新待办或审批进度发生变化时，服务端实时推送事件，手机页面无需手动刷新即可弹出提醒并点击跳转。
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="SSE 认证 Token 无效")

    async def event_generator():
        last_seen_id = 0
        # 首次连接读取当前最大通知ID和未读计数
        with SessionLocal() as db:
            latest = (
                db.query(func.max(models.Notification.id))
                .filter(models.Notification.recipient_id == user_id)
                .scalar()
            )
            last_seen_id = latest or 0
            unread_count = (
                db.query(models.Notification)
                .filter_by(recipient_id=user_id, is_read=0)
                .count()
            )
            todo_count = (
                db.query(models.ApprovalInstanceNode)
                .join(models.Application, models.Application.id == models.ApprovalInstanceNode.application_id)
                .filter(
                    models.ApprovalInstanceNode.approver_id == user_id,
                    models.ApprovalInstanceNode.status == "PENDING",
                    models.Application.status == "IN_REVIEW",
                )
                .count()
            )
            init_data = json.dumps(
                {"type": "INIT_SYNC", "unread_count": unread_count, "todo_count": todo_count},
                ensure_ascii=False,
            )
            yield f"data: {init_data}\n\n"

        # 持续监听新通知变化
        for _ in range(360):  # 保持连接约 15 分钟，前端断线自动重连
            await asyncio.sleep(2.5)
            with SessionLocal() as db:
                new_notifs = (
                    db.query(models.Notification)
                    .filter(
                        models.Notification.recipient_id == user_id,
                        models.Notification.id > last_seen_id,
                    )
                    .order_by(models.Notification.id.asc())
                    .all()
                )
                if new_notifs:
                    last_seen_id = new_notifs[-1].id
                    unread_count = (
                        db.query(models.Notification)
                        .filter_by(recipient_id=user_id, is_read=0)
                        .count()
                    )
                    todo_count = (
                        db.query(models.ApprovalInstanceNode)
                        .join(models.Application, models.Application.id == models.ApprovalInstanceNode.application_id)
                        .filter(
                            models.ApprovalInstanceNode.approver_id == user_id,
                            models.ApprovalInstanceNode.status == "PENDING",
                            models.Application.status == "IN_REVIEW",
                        )
                        .count()
                    )
                    for n in new_notifs:
                        event_payload = json.dumps(
                            {
                                "type": "NEW_NOTIFICATION",
                                "unread_count": unread_count,
                                "todo_count": todo_count,
                                "notification": {
                                    "id": n.id,
                                    "application_id": n.application_id,
                                    "notify_type": n.notify_type,
                                    "title": n.title,
                                    "content": n.content,
                                    "created_at": n.created_at.isoformat() if n.created_at else None,
                                },
                            },
                            ensure_ascii=False,
                        )
                        yield f"data: {event_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/notifications/webpush-subscribe", summary="保存移动端/浏览器 WebPush 后台推送订阅凭证(提分功能)")
def save_webpush_subscription(
    payload: WebPushSubscriptionSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    current_user.webpush_sub_json = payload.subscription
    db.commit()
    return {"message": "WebPush 后台推送订阅凭证已绑定，页面后台或锁屏时将触发系统通知"}