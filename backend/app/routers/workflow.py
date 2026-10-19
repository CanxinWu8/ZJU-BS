from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import update
from pydantic import BaseModel, Field

from app.database import get_db
from app import models
from app.auth import get_current_user
from app.routers.applications import create_notification_idempotent, generate_unique_app_no

router = APIRouter(prefix="/api/v1/workflow", tags=["Workflow State Machine & Delegation"])


# ==================== Pydantic 请求模型 ====================

class ApproveRejectRequest(BaseModel):
    comment: Optional[str] = Field(default="", description="审批意见(驳回时必填)")
    expected_version: Optional[int] = Field(default=None, description="乐观锁版本号，防并发冲突与重复点击")


class WithdrawRequest(BaseModel):
    reason: Optional[str] = Field(default="申请人主动撤回", description="撤回原因说明")
    expected_version: Optional[int] = Field(default=None, description="乐观锁版本号，防撤回与审批并发冲突")


class UrgeRequest(BaseModel):
    message: Optional[str] = Field(default="请尽快协助处理审批，谢谢！", max_length=200)


class DelegationCreateRequest(BaseModel):
    delegatee_id: int = Field(..., description="代理人用户ID")
    start_time: datetime
    end_time: datetime
    reason: Optional[str] = Field(default="出差/休假期间委托代审", max_length=255)


# ==================== 1. 批准、驳回、撤回、重提与催办接口 ====================

@router.post("/applications/{app_id}/approve", summary="当前节点审批人批准申请(含乐观锁并发控制)")
def approve_application(
    app_id: int,
    payload: ApproveRejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    app_obj = db.query(models.Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="申请单不存在")

    if app_obj.status != "IN_REVIEW":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"操作失败：当前申请状态已变更为【{app_obj.status}】，无法继续审批",
        )

    # 任何人不得审批自己的申请
    if app_obj.applicant_id == current_user.id:
        raise HTTPException(status_code=403, detail="违反业务安全规则：任何人不得审批自己提交的申请")

    # 查找当前激活的顺序节点
    cur_node = (
        db.query(models.ApprovalInstanceNode)
        .filter_by(application_id=app_obj.id, node_seq=app_obj.current_node_seq, status="PENDING")
        .first()
    )
    if not cur_node:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前待办节点已被处理或状态已变化，请刷新页面",
        )

    if cur_node.approver_id != current_user.id:
        raise HTTPException(status_code=403, detail="权限不足：您不是当前待办节点的指定审批人，不能越权或提前审批")

    check_ver = payload.expected_version if payload.expected_version is not None else app_obj.version

    # 查找是否存在下一顺序节点
    next_node = (
        db.query(models.ApprovalInstanceNode)
        .filter_by(application_id=app_obj.id, node_seq=app_obj.current_node_seq + 1)
        .first()
    )

    now = datetime.now()
    new_status = "IN_REVIEW" if next_node else "APPROVED"
    next_seq = next_node.node_seq if next_node else app_obj.current_node_seq

    # 使用数据库原子条件更新实现乐观锁（防止重复点击、两个浏览器并发审批或与撤回并发冲突）
    stmt = (
        update(models.Application)
        .where(
            models.Application.id == app_obj.id,
            models.Application.status == "IN_REVIEW",
            models.Application.current_node_seq == cur_node.node_seq,
            models.Application.version == check_ver,
        )
        .values(
            status=new_status,
            current_node_seq=next_seq,
            version=check_ver + 1,
            completed_at=now if new_status == "APPROVED" else None,
            updated_at=now,
        )
    )
    res = db.execute(stmt)
    if res.rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="并发冲突拦截：该申请刚刚已被撤回或已在其他窗口处理，请刷新后查看最新状态",
        )

    # 更新当前节点状态
    cur_node.status = "APPROVED"
    cur_node.comment = (payload.comment or "同意").strip()
    cur_node.acted_at = now

    tpl_ver_num = (app_obj.snapshot_json or {}).get("template_version", 1)

    # 激活下一节点或完成整个流程
    if next_node:
        next_node.status = "PENDING"
        create_notification_idempotent(
            db=db,
            recipient_id=next_node.approver_id,
            application_id=app_obj.id,
            notify_type="NEW_TODO",
            title=f"新审批待办：{app_obj.title}",
            content=f"上一节点【{cur_node.node_name}】已通过，请您处理《{app_obj.title}》({app_obj.app_no})。",
            idempotency_key=f"app_{app_obj.id}_ver_{check_ver + 1}_node_{next_node.node_seq}_todo",
        )
    else:
        create_notification_idempotent(
            db=db,
            recipient_id=app_obj.applicant_id,
            application_id=app_obj.id,
            notify_type="APPROVED",
            title=f"申请已通过：{app_obj.title}",
            content=f"您提交的《{app_obj.title}》({app_obj.app_no}) 已完成全部审批节点并正式通过！",
            idempotency_key=f"app_{app_obj.id}_ver_{check_ver + 1}_approved",
        )

    # 写入不可篡改审批日志
    db.add(
        models.ApprovalLog(
            application_id=app_obj.id,
            template_version=tpl_ver_num,
            node_seq=cur_node.node_seq,
            node_name=cur_node.node_name,
            operator_id=current_user.id,
            action="APPROVE",
            comment=cur_node.comment,
            result_status=new_status,
            ip_address=request.client.host if request.client else None,
        )
    )

    db.commit()
    return {
        "message": "节点审批通过，已流转至下一节点" if next_node else "终审通过，审批流程已完成",
        "app_id": app_obj.id,
        "new_status": new_status,
        "current_node_seq": next_seq,
        "version": check_ver + 1,
    }


@router.post("/applications/{app_id}/reject", summary="当前节点审批人驳回申请(必填理由)")
def reject_application(
    app_id: int,
    payload: ApproveRejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    reason = (payload.comment or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="驳回申请时必须填写明确的驳回理由")

    app_obj = db.query(models.Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="申请单不存在")

    if app_obj.status != "IN_REVIEW":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"操作失败：当前申请状态已变更为【{app_obj.status}】，无法执行驳回",
        )

    if app_obj.applicant_id == current_user.id:
        raise HTTPException(status_code=403, detail="任何人不得审批自己的申请")

    cur_node = (
        db.query(models.ApprovalInstanceNode)
        .filter_by(application_id=app_obj.id, node_seq=app_obj.current_node_seq, status="PENDING")
        .first()
    )
    if not cur_node or cur_node.approver_id != current_user.id:
        raise HTTPException(status_code=403, detail="权限不足：您不是当前待办节点的指定审批人")

    check_ver = payload.expected_version if payload.expected_version is not None else app_obj.version
    now = datetime.now()

    stmt = (
        update(models.Application)
        .where(
            models.Application.id == app_obj.id,
            models.Application.status == "IN_REVIEW",
            models.Application.current_node_seq == cur_node.node_seq,
            models.Application.version == check_ver,
        )
        .values(
            status="REJECTED",
            version=check_ver + 1,
            completed_at=now,
            updated_at=now,
        )
    )
    res = db.execute(stmt)
    if res.rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="并发冲突拦截：该申请状态已变化（可能已被撤回或处理），请刷新页面",
        )

    cur_node.status = "REJECTED"
    cur_node.comment = reason
    cur_node.acted_at = now

    # 后续未到达节点全部标记为 CANCELED
    db.query(models.ApprovalInstanceNode).filter(
        models.ApprovalInstanceNode.application_id == app_obj.id,
        models.ApprovalInstanceNode.status == "WAITING",
    ).update({"status": "CANCELED"}, synchronize_session=False)

    tpl_ver_num = (app_obj.snapshot_json or {}).get("template_version", 1)
    db.add(
        models.ApprovalLog(
            application_id=app_obj.id,
            template_version=tpl_ver_num,
            node_seq=cur_node.node_seq,
            node_name=cur_node.node_name,
            operator_id=current_user.id,
            action="REJECT",
            comment=reason,
            result_status="REJECTED",
            ip_address=request.client.host if request.client else None,
        )
    )

    create_notification_idempotent(
        db=db,
        recipient_id=app_obj.applicant_id,
        application_id=app_obj.id,
        notify_type="REJECTED",
        title=f"申请被驳回：{app_obj.title}",
        content=f"您的申请《{app_obj.title}》({app_obj.app_no}) 在节点【{cur_node.node_name}】被 {current_user.real_name} 驳回。理由：{reason}",
        idempotency_key=f"app_{app_obj.id}_ver_{check_ver + 1}_rejected",
    )

    db.commit()
    return {
        "message": "申请已驳回并通知申请人",
        "app_id": app_obj.id,
        "new_status": "REJECTED",
        "version": check_ver + 1,
    }


@router.post("/applications/{app_id}/withdraw", summary="申请人撤回审批中的申请(含并发冲突检测)")
def withdraw_application(
    app_id: int,
    payload: WithdrawRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    app_obj = db.query(models.Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="申请单不存在")

    if app_obj.applicant_id != current_user.id:
        raise HTTPException(status_code=403, detail="权限不足：只能撤回本人提交的申请")

    if app_obj.status != "IN_REVIEW":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"无法撤回：当前申请状态为【{app_obj.status}】（仅审批中的申请允许撤回）",
        )

    check_ver = payload.expected_version if payload.expected_version is not None else app_obj.version
    now = datetime.now()

    cur_pending_node = (
        db.query(models.ApprovalInstanceNode)
        .filter_by(application_id=app_obj.id, status="PENDING")
        .first()
    )
    pending_approver_id = cur_pending_node.approver_id if cur_pending_node else None

    stmt = (
        update(models.Application)
        .where(
            models.Application.id == app_obj.id,
            models.Application.status == "IN_REVIEW",
            models.Application.version == check_ver,
        )
        .values(
            status="WITHDRAWN",
            version=check_ver + 1,
            completed_at=now,
            updated_at=now,
        )
    )
    res = db.execute(stmt)
    if res.rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="并发冲突拦截：当前审批人刚刚已完成审批，状态已变更，无法撤回",
        )

    # 原待办全部失效，已审批历史保留
    db.query(models.ApprovalInstanceNode).filter(
        models.ApprovalInstanceNode.application_id == app_obj.id,
        models.ApprovalInstanceNode.status.in_(["PENDING", "WAITING"]),
    ).update({"status": "CANCELED"}, synchronize_session=False)

    tpl_ver_num = (app_obj.snapshot_json or {}).get("template_version", 1)
    db.add(
        models.ApprovalLog(
            application_id=app_obj.id,
            template_version=tpl_ver_num,
            node_seq=app_obj.current_node_seq,
            node_name="申请人撤回",
            operator_id=current_user.id,
            action="WITHDRAW",
            comment=(payload.reason or "申请人主动撤回").strip(),
            result_status="WITHDRAWN",
            ip_address=request.client.host if request.client else None,
        )
    )

    if pending_approver_id:
        create_notification_idempotent(
            db=db,
            recipient_id=pending_approver_id,
            application_id=app_obj.id,
            notify_type="WITHDRAWN",
            title=f"待办已撤回：{app_obj.title}",
            content=f"申请人 {current_user.real_name} 已主动撤回《{app_obj.title}》({app_obj.app_no})，原待办已失效。",
            idempotency_key=f"app_{app_obj.id}_ver_{check_ver + 1}_withdrawn",
        )

    db.commit()
    return {
        "message": "申请已成功撤回，原待办已失效",
        "app_id": app_obj.id,
        "new_status": "WITHDRAWN",
        "version": check_ver + 1,
    }


@router.post("/applications/{app_id}/resubmit-copy", status_code=status.HTTP_201_CREATED, summary="已驳回/已撤回申请一键复制生成新草稿并关联原单")
def copy_for_resubmit(
    app_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    orig = db.query(models.Application).filter_by(id=app_id).first()
    if not orig or orig.applicant_id != current_user.id:
        raise HTTPException(status_code=404, detail="原申请不存在或无权复制")

    if orig.status not in ("REJECTED", "WITHDRAWN"):
        raise HTTPException(status_code=400, detail="只有【已驳回】或【已撤回】的申请才需要复制重新提交")

    new_app = models.Application(
        app_no=generate_unique_app_no(db, orig.category),
        category=orig.category,
        template_id=orig.template_id,
        template_version_id=orig.template_version_id,
        title=f"{orig.title} (重提)",
        applicant_id=current_user.id,
        department_id=current_user.department_id,
        status="DRAFT",
        total_amount_cents=orig.total_amount_cents,
        current_node_seq=0,
        ref_application_id=orig.ref_application_id,
        copied_from_id=orig.id,
        biz_payload=dict(orig.biz_payload or {}),
        has_risk_warning=orig.has_risk_warning,
        version=1,
    )
    db.add(new_app)
    db.flush()

    # 复制采购明细与比价记录
    for pi in db.query(models.ProcurementItem).filter_by(application_id=orig.id).all():
        db.add(
            models.ProcurementItem(
                application_id=new_app.id,
                item_name=pi.item_name,
                specification=pi.specification,
                quantity=pi.quantity,
                unit=pi.unit,
                unit_price_cents=pi.unit_price_cents,
                subtotal_cents=pi.subtotal_cents,
            )
        )
    for pq in db.query(models.ProcurementQuote).filter_by(application_id=orig.id).all():
        db.add(
            models.ProcurementQuote(
                application_id=new_app.id,
                supplier_name=pq.supplier_name,
                quote_date=pq.quote_date,
                quoted_amount_cents=pq.quoted_amount_cents,
                purchase_url=pq.purchase_url,
                is_selected=pq.is_selected,
                attachment_id=pq.attachment_id,
            )
        )
    # 复制报销明细
    for ei in db.query(models.ExpenseItem).filter_by(application_id=orig.id).all():
        db.add(
            models.ExpenseItem(
                application_id=new_app.id,
                expense_type=ei.expense_type,
                occur_date=ei.occur_date,
                description=ei.description,
                amount_cents=ei.amount_cents,
                is_no_invoice=ei.is_no_invoice,
                no_invoice_reason=ei.no_invoice_reason,
                invoice_numbers=ei.invoice_numbers,
            )
        )

    db.add(
        models.ApprovalLog(
            application_id=new_app.id,
            template_version=1,
            node_seq=0,
            node_name="复制重提",
            operator_id=current_user.id,
            action="RESUBMIT",
            comment=f"基于原申请单 {orig.app_no}(ID={orig.id}) 复制生成新申请草稿",
            result_status="DRAFT",
            ip_address=request.client.host if request.client else None,
        )
    )

    db.commit()
    return {
        "message": f"已基于原单 {orig.app_no} 复制生成新草稿，修改后即可重新提交",
        "new_application_id": new_app.id,
        "new_app_no": new_app.app_no,
        "copied_from_id": orig.id,
    }


@router.post("/applications/{app_id}/urge", summary="申请人对当前待办审批人发起催办提醒(增强功能)")
def urge_application(
    app_id: int,
    payload: UrgeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    app_obj = db.query(models.Application).filter_by(id=app_id).first()
    if not app_obj or app_obj.applicant_id != current_user.id:
        raise HTTPException(status_code=404, detail="申请不存在或仅申请人本人可发起催办")

    if app_obj.status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail="只有处于【审批中】的申请才能发起催办")

    cur_node = (
        db.query(models.ApprovalInstanceNode)
        .filter_by(application_id=app_obj.id, status="PENDING")
        .first()
    )
    if not cur_node:
        raise HTTPException(status_code=400, detail="未找到当前激活的审批节点")

    urge_count = (
        db.query(models.ApprovalLog)
        .filter_by(application_id=app_obj.id, node_seq=cur_node.node_seq, action="URGE")
        .count()
    )

    db.add(
        models.ApprovalLog(
            application_id=app_obj.id,
            template_version=1,
            node_seq=cur_node.node_seq,
            node_name=cur_node.node_name,
            operator_id=current_user.id,
            action="URGE",
            comment=f"申请人催办：{payload.message}",
            result_status="IN_REVIEW",
            ip_address=request.client.host if request.client else None,
        )
    )

    create_notification_idempotent(
        db=db,
        recipient_id=cur_node.approver_id,
        application_id=app_obj.id,
        notify_type="URGE_REMINDER",
        title=f"⚡ 催办提醒：{app_obj.title}",
        content=f"申请人 {current_user.real_name} 提醒您尽快审批《{app_obj.title}》({app_obj.app_no})：{payload.message}",
        idempotency_key=f"app_{app_obj.id}_node_{cur_node.node_seq}_urge_{urge_count + 1}",
    )

    db.commit()
    return {"message": "已向当前节点审批人发送催办提醒并记录日志"}


# ==================== 2. 审批委托配置接口 (增强功能) ====================

@router.get("/delegations", summary="查看本人配置的审批委托规则及同事列表")
def list_my_delegations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rows = (
        db.query(models.ApprovalDelegation)
        .filter_by(delegator_id=current_user.id)
        .order_by(models.ApprovalDelegation.id.desc())
        .all()
    )
    users_map = {u.id: u.real_name for u in db.query(models.User).filter_by(status="ACTIVE").all()}
    return {
        "available_users": [
            {"id": uid, "real_name": uname}
            for uid, uname in users_map.items()
            if uid != current_user.id
        ],
        "delegations": [
            {
                "id": r.id,
                "delegator_id": r.delegator_id,
                "delegatee_id": r.delegatee_id,
                "delegatee_name": users_map.get(r.delegatee_id, ""),
                "start_time": r.start_time,
                "end_time": r.end_time,
                "is_active": r.is_active,
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.post("/delegations", status_code=status.HTTP_201_CREATED, summary="创建审批委托规则并自动转交当前待办")
def create_delegation(
    payload: DelegationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if payload.delegatee_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能将审批权限委托给自己")

    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="委托结束时间必须晚于开始时间")

    delegatee = db.query(models.User).filter_by(id=payload.delegatee_id, status="ACTIVE").first()
    if not delegatee:
        raise HTTPException(status_code=404, detail="指定的代理人不存在或未激活")

    # 停用本人旧的激活委托
    db.query(models.ApprovalDelegation).filter_by(delegator_id=current_user.id, is_active=1).update(
        {"is_active": 0}
    )

    del_obj = models.ApprovalDelegation(
        delegator_id=current_user.id,
        delegatee_id=delegatee.id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_active=1,
        reason=payload.reason,
    )
    db.add(del_obj)

    # 若当前时间处于生效期内，自动将名下非代理人本人提交的 PENDING 待办转交给代理人并留痕
    now = datetime.now()
    transferred_count = 0
    if payload.start_time <= now <= payload.end_time:
        pending_nodes = (
            db.query(models.ApprovalInstanceNode, models.Application)
            .join(models.Application, models.Application.id == models.ApprovalInstanceNode.application_id)
            .filter(
                models.ApprovalInstanceNode.approver_id == current_user.id,
                models.ApprovalInstanceNode.status == "PENDING",
                models.Application.status == "IN_REVIEW",
                models.Application.applicant_id != delegatee.id,
            )
            .all()
        )
        for node, app_obj in pending_nodes:
            node.delegated_from_id = current_user.id
            node.approver_id = delegatee.id
            transferred_count += 1
            db.add(
                models.ApprovalLog(
                    application_id=app_obj.id,
                    template_version=1,
                    node_seq=node.node_seq,
                    node_name=node.node_name,
                    operator_id=current_user.id,
                    action="DELEGATE",
                    comment=f"审批委托转交：{current_user.real_name} 委托 {delegatee.real_name} 代为审批 ({payload.reason})",
                    result_status="IN_REVIEW",
                    ip_address=request.client.host if request.client else None,
                )
            )

    db.commit()
    return {
        "message": f"审批委托已生效（自动转交现有待办 {transferred_count} 笔）",
        "delegation_id": del_obj.id,
    }