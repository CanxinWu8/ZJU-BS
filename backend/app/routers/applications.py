from datetime import datetime, date
import uuid
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, Field

from app.database import get_db
from app import models
from app.auth import get_current_user, get_user_role_codes
from app.routers.attachments import check_duplicate_invoice

router = APIRouter(prefix="/api/v1/applications", tags=["Applications & Business Rules"])

EXPENSE_TYPES = {"TRAFFIC", "HOTEL", "MEAL", "OFFICE", "OTHER"}
CATEGORY_PREFIX = {
    "PROCUREMENT": "PUR",
    "TRAVEL": "TRV",
    "EXPENSE": "EXP",
    "CUSTOM": "CUS",
}


# ==================== Pydantic 请求模型 ====================

class ProcurementItemInput(BaseModel):
    item_name: str = Field(..., min_length=1, max_length=128)
    specification: str = Field(..., min_length=1, max_length=128)
    quantity: int = Field(..., gt=0)
    unit: str = Field(..., min_length=1, max_length=32)
    unit_price_cents: int = Field(..., gt=0, description="预计单价(分)")


class ProcurementQuoteInput(BaseModel):
    supplier_name: str = Field(..., min_length=1, max_length=128)
    quote_date: date
    quoted_amount_cents: int = Field(..., gt=0, description="报价总额(分)")
    purchase_url: Optional[str] = None
    is_selected: bool = False
    attachment_id: Optional[int] = None


class ExpenseItemInput(BaseModel):
    expense_type: str = Field(..., description="TRAFFIC, HOTEL, MEAL, OFFICE, OTHER")
    occur_date: date
    description: str = Field(..., min_length=1, max_length=255)
    amount_cents: int = Field(..., gt=0, description="费用金额(分，必须>0)")
    is_no_invoice: bool = False
    no_invoice_reason: Optional[str] = None
    attachment_ids: List[int] = Field(default_factory=list, description="关联的票据附件ID列表")


class ApplicationSaveRequest(BaseModel):
    id: Optional[int] = Field(default=None, description="草稿更新时传入已有申请ID")
    template_code: str = Field(..., description="PROCUREMENT_STD, TRAVEL_STD, EXPENSE_STD 或自定义编码")
    title: str = Field(..., min_length=2, max_length=200)
    action: str = Field(default="SUBMIT", pattern="^(SAVE_DRAFT|SUBMIT)$")
    ref_application_id: Optional[int] = Field(default=None, description="报销关联的已批准差旅/采购申请ID")
    biz_payload: Dict[str, Any] = Field(default_factory=dict, description="业务主字段或自定义表单键值对")
    attachment_ids: List[int] = Field(default_factory=list, description="通用补充附件ID列表")
    procurement_items: List[ProcurementItemInput] = Field(default_factory=list)
    procurement_quotes: List[ProcurementQuoteInput] = Field(default_factory=list)
    expense_items: List[ExpenseItemInput] = Field(default_factory=list)


# ==================== 核心辅助函数 ====================

def generate_unique_app_no(db: Session, category: str) -> str:
    """生成全局唯一申请编号: 前缀-YYYYMMDD-4位序号"""
    prefix = CATEGORY_PREFIX.get(category, "APP")
    today_str = datetime.now().strftime("%Y%m%d")
    like_pattern = f"{prefix}-{today_str}-%"
    count = db.query(models.Application).filter(models.Application.app_no.like(like_pattern)).count()
    seq_str = f"{count + 1:04d}"
    candidate = f"{prefix}-{today_str}-{seq_str}"
    while db.query(models.Application).filter_by(app_no=candidate).first():
        candidate = f"{prefix}-{today_str}-{uuid.uuid4().hex[:6].upper()}"
    return candidate


def create_notification_idempotent(
    db: Session,
    recipient_id: int,
    application_id: int,
    notify_type: str,
    title: str,
    content: str,
    idempotency_key: str,
):
    """创建持久化站内通知（通过 idempotency_key 保证重试绝不产生重复通知）"""
    exists = db.query(models.Notification).filter_by(idempotency_key=idempotency_key).first()
    if not exists:
        db.add(
            models.Notification(
                recipient_id=recipient_id,
                application_id=application_id,
                notify_type=notify_type,
                title=title,
                content=content,
                idempotency_key=idempotency_key,
                is_read=0,
            )
        )


def resolve_node_approver(
    db: Session,
    rule_type: str,
    rule_value: Any,
    applicant: models.User,
) -> tuple[int, Optional[int]]:
    """
    将节点规则解析为具体审批人用户ID，并处理：
    1. 严禁自我审批（若解析出的部门负责人或角色持有者是申请人本人，自动上浮至企业负责人或同角色其他成员）
    2. 生效中的审批委托（自动转交代理人并记录原审批人ID）
    """
    raw_approver_id: Optional[int] = None

    if rule_type == "DEPT_MANAGER":
        dept = db.query(models.Department).filter_by(id=applicant.department_id).first()
        if not dept or not dept.manager_user_id:
            raise HTTPException(status_code=400, detail="申请人所属部门尚未配置部门负责人")
        raw_approver_id = dept.manager_user_id

    elif rule_type == "USER":
        raw_approver_id = int(rule_value)

    elif rule_type == "ROLE":
        role = db.query(models.Role).filter_by(code=str(rule_value)).first()
        if not role:
            raise HTTPException(status_code=400, detail=f"审批角色 {rule_value} 不存在")
        holders = (
            db.query(models.User.id)
            .join(models.UserRole, models.UserRole.user_id == models.User.id)
            .filter(models.UserRole.role_id == role.id, models.User.status == "ACTIVE")
            .order_by(models.User.id.asc())
            .all()
        )
        holder_ids = [h[0] for h in holders]
        if not holder_ids:
            raise HTTPException(status_code=400, detail=f"角色 {rule_value} 当前无有效审批人")
        # 优先选择非申请人本人的角色持有者
        non_self = [uid for uid in holder_ids if uid != applicant.id]
        raw_approver_id = non_self[0] if non_self else holder_ids[0]

    # 自我审批规避：若解析出的审批人恰好是申请人本人，上浮至企业负责人(EXECUTIVE)
    if raw_approver_id == applicant.id:
        exec_role = db.query(models.Role).filter_by(code="EXECUTIVE").first()
        exec_holder = (
            db.query(models.User.id)
            .join(models.UserRole, models.UserRole.user_id == models.User.id)
            .filter(
                models.UserRole.role_id == exec_role.id,
                models.User.status == "ACTIVE",
                models.User.id != applicant.id,
            )
            .first()
            if exec_role
            else None
        )
        if exec_holder:
            raw_approver_id = exec_holder[0]
        else:
            # 若连企业负责人自己提申请，则交由财务负责人或其他部门负责人交叉审批，确保绝不自批
            fallback_mgr = (
                db.query(models.User.id)
                .join(models.UserRole, models.UserRole.user_id == models.User.id)
                .join(models.Role, models.Role.id == models.UserRole.role_id)
                .filter(
                    models.Role.code.in_(["FINANCE", "DEPT_MANAGER"]),
                    models.User.status == "ACTIVE",
                    models.User.id != applicant.id,
                )
                .first()
            )
            if not fallback_mgr:
                raise HTTPException(status_code=400, detail="系统要求任何人不得审批自己的申请，且未找到可用的上级/交叉审批人")
            raw_approver_id = fallback_mgr[0]

    # 检查是否存在当前生效的审批委托
    now = datetime.now()
    delegation = (
        db.query(models.ApprovalDelegation)
        .filter(
            models.ApprovalDelegation.delegator_id == raw_approver_id,
            models.ApprovalDelegation.is_active == 1,
            models.ApprovalDelegation.start_time <= now,
            models.ApprovalDelegation.end_time >= now,
        )
        .first()
    )
    if delegation and delegation.delegatee_id != applicant.id:
        return delegation.delegatee_id, raw_approver_id

    return raw_approver_id, None


def validate_and_calculate_business_rules(
    db: Session,
    category: str,
    tpl_ver: models.WorkflowTemplateVersion,
    payload: ApplicationSaveRequest,
    applicant: models.User,
    is_submit: bool,
    current_app_id: Optional[int],
) -> tuple[int, Dict[str, Any], int]:
    """
    执行四大类业务规则校验并由服务端精确计算总金额（单位：整数分）
    返回: (total_amount_cents, enriched_biz_payload, has_risk_warning)
    """
    biz = dict(payload.biz_payload or {})
    total_cents = 0
    has_risk = 0

    if category == "PROCUREMENT":
        if is_submit and len(payload.procurement_items) < 2:
            raise HTTPException(status_code=400, detail="采购申请提交时至少需要包含 2 条采购明细")

        for item in payload.procurement_items:
            total_cents += item.quantity * item.unit_price_cents

        if is_submit:
            budget_limit = int(biz.get("budget_limit_cents", 0))
            if budget_limit > 0 and total_cents > budget_limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"采购明细合计金额({total_cents / 100:.2f}元)超出预算上限({budget_limit / 100:.2f}元)",
                )

            is_single_source = bool(biz.get("is_single_source", False))
            if is_single_source:
                if len(payload.procurement_quotes) < 1:
                    raise HTTPException(status_code=400, detail="单一来源采购也必须录入至少 1 家供应商报价")
                reason = str(biz.get("single_source_reason", "")).strip()
                if len(reason) < 5:
                    raise HTTPException(status_code=400, detail="单一来源采购必须详细填写【单一来源说明】")
                has_risk = 1  # 单一来源在审批端醒目提示
            else:
                if len(payload.procurement_quotes) < 2:
                    raise HTTPException(status_code=400, detail="标准采购必须提供至少 2 家供应商报价进行比较")

            selected_quotes = [q for q in payload.procurement_quotes if q.is_selected]
            if len(selected_quotes) != 1:
                raise HTTPException(status_code=400, detail="必须在供应商报价中明确勾选唯一 1 家【拟选供应商】")

            selected_q = selected_quotes[0]
            min_quote_cents = min(q.quoted_amount_cents for q in payload.procurement_quotes)
            if selected_q.quoted_amount_cents > min_quote_cents:
                non_lowest_reason = str(biz.get("non_lowest_reason", "")).strip()
                if not non_lowest_reason:
                    raise HTTPException(
                        status_code=400,
                        detail="拟选供应商报价高于最低报价，必须填写【未选最低价理由】",
                    )
                has_risk = 1

            biz["selected_supplier_name"] = selected_q.supplier_name
            biz["selected_quote_cents"] = selected_q.quoted_amount_cents
            biz["min_quote_cents"] = min_quote_cents

    elif category == "TRAVEL":
        budget_cents = int(biz.get("budget_cents", 0))
        if budget_cents < 0:
            raise HTTPException(status_code=400, detail="差旅费用预算不得为负数")
        total_cents = budget_cents

        start_str = biz.get("start_date")
        end_str = biz.get("end_date")
        if is_submit and (not start_str or not end_str):
            raise HTTPException(status_code=400, detail="差旅申请必须填写开始日期和结束日期")

        if start_str and end_str:
            try:
                s_date = date.fromisoformat(str(start_str)[:10])
                e_date = date.fromisoformat(str(end_str)[:10])
            except ValueError:
                raise HTTPException(status_code=400, detail="差旅起止日期格式无效，应为 YYYY-MM-DD")
            if e_date < s_date:
                raise HTTPException(status_code=400, detail="差旅结束日期不得早于开始日期")
            duration_days = (e_date - s_date).days + 1
            biz["duration_days"] = duration_days
            biz["duration_caliber"] = "自然日口径 (结束日期 - 开始日期 + 1天)"

        if is_submit:
            for req_key, label in [("departure", "出发地点"), ("destination", "目的地点"), ("purpose", "出差目的")]:
                if not str(biz.get(req_key, "")).strip():
                    raise HTTPException(status_code=400, detail=f"差旅申请必须填写{label}")

    elif category == "EXPENSE":
        if is_submit and len(payload.expense_items) < 3:
            raise HTTPException(status_code=400, detail="报销申请提交时至少需要包含 3 条费用明细")

        # 若关联了前置差旅或采购申请，校验必须是本人且已批准(APPROVED)
        if payload.ref_application_id:
            ref_app = db.query(models.Application).filter_by(id=payload.ref_application_id).first()
            if not ref_app:
                raise HTTPException(status_code=400, detail="关联的前置申请单不存在")
            if ref_app.applicant_id != applicant.id:
                raise HTTPException(status_code=403, detail="只能关联本人提交的差旅或采购申请")
            if ref_app.status != "APPROVED" or ref_app.category not in ("TRAVEL", "PROCUREMENT"):
                raise HTTPException(status_code=400, detail="只能关联状态为【已通过】的差旅或采购申请")
            biz["ref_app_no"] = ref_app.app_no
            biz["ref_app_title"] = ref_app.title
            biz["ref_app_category"] = ref_app.category
            biz["ref_app_amount_cents"] = ref_app.total_amount_cents
        elif is_submit:
            if not str(biz.get("expense_desc", "")).strip():
                raise HTTPException(status_code=400, detail="独立报销必须填写详细的报销事由说明")

        # 票据防重与无票例外校验
        used_att_ids_in_this_app = set()
        used_sha256_in_this_app = set()
        used_inv_no_in_this_app = set()
        cross_app_warnings = []

        for idx, item in enumerate(payload.expense_items, start=1):
            if item.expense_type not in EXPENSE_TYPES:
                raise HTTPException(status_code=400, detail=f"明细 #{idx} 费用类型无效: {item.expense_type}")
            if item.amount_cents <= 0:
                raise HTTPException(status_code=400, detail=f"明细 #{idx} 金额必须大于 0")
            total_cents += item.amount_cents

            if is_submit:
                if item.is_no_invoice:
                    if not item.no_invoice_reason or len(item.no_invoice_reason.strip()) < 2:
                        raise HTTPException(status_code=400, detail=f"明细 #{idx} 勾选了无票支出，必须填写无票原因")
                    has_risk = 1  # 无票支出在财务界面高亮预警
                else:
                    if not item.attachment_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"明细 #{idx} 未上传票据附件（若确无票据请勾选无票例外并说明原因）",
                        )

            for att_id in item.attachment_ids:
                if att_id in used_att_ids_in_this_app:
                    raise HTTPException(status_code=400, detail=f"同一张报销单内不能重复使用同一份票据记录(附件ID={att_id})")
                used_att_ids_in_this_app.add(att_id)

                att_obj = db.query(models.Attachment).filter_by(id=att_id).first()
                if not att_obj or att_obj.uploaded_by != applicant.id:
                    raise HTTPException(status_code=400, detail=f"明细 #{idx} 绑定的票据附件不存在或无权使用")

                if att_obj.file_sha256 in used_sha256_in_this_app:
                    raise HTTPException(status_code=400, detail=f"同一张报销单内检测到两份内容完全相同的票据文件({att_obj.original_name})")
                used_sha256_in_this_app.add(att_obj.file_sha256)

                if att_obj.invoice_no:
                    if att_obj.invoice_no in used_inv_no_in_this_app:
                        raise HTTPException(status_code=400, detail=f"同一张报销单内发票号码重复: {att_obj.invoice_no}")
                    used_inv_no_in_this_app.add(att_obj.invoice_no)

                # 检测跨单重复票据预警
                dup_list = check_duplicate_invoice(db, att_obj.file_sha256, att_obj.invoice_no, exclude_app_id=current_app_id)
                if dup_list:
                    has_risk = 1
                    cross_app_warnings.extend(dup_list)

        if cross_app_warnings:
            biz["duplicate_invoice_warnings"] = cross_app_warnings

    elif category == "CUSTOM":
        # 根据模板 form_schema 动态校验字段
        fields_def = (tpl_ver.form_schema or {}).get("fields", [])
        for f in fields_def:
            f_key = f["field_key"]
            f_label = f["label"]
            f_type = f["type"]
            val = biz.get(f_key)

            if is_submit and f.get("required") and (val is None or str(val).strip() == ""):
                raise HTTPException(status_code=400, detail=f"自定义表单必填项未填写: 【{f_label}】")

            if val is not None and str(val).strip() != "":
                if f_type == "number":
                    try:
                        num_val = float(val)
                    except ValueError:
                        raise HTTPException(status_code=400, detail=f"字段【{f_label}】必须为有效数字")
                    if f.get("min_value") is not None and num_val < f["min_value"]:
                        raise HTTPException(status_code=400, detail=f"字段【{f_label}】不能小于 {f['min_value']}")
                    if f.get("max_value") is not None and num_val > f["max_value"]:
                        raise HTTPException(status_code=400, detail=f"字段【{f_label}】不能大于 {f['max_value']}")
                    if "amount" in f_key or "cents" in f_key:
                        total_cents = int(num_val)
                elif f_type == "radio" and f.get("options"):
                    if str(val) not in f["options"]:
                        raise HTTPException(status_code=400, detail=f"字段【{f_label}】的值不在允许的选项范围内")

    return total_cents, biz, has_risk


# ==================== API 路由实现 ====================

@router.get("/linkable", summary="获取当前用户已批准的差旅/采购申请列表(供报销关联选择)")
def list_linkable_applications(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    apps = (
        db.query(models.Application)
        .filter(
            models.Application.applicant_id == current_user.id,
            models.Application.status == "APPROVED",
            models.Application.category.in_(["TRAVEL", "PROCUREMENT"]),
        )
        .order_by(models.Application.id.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "app_no": a.app_no,
            "category": a.category,
            "title": a.title,
            "total_amount_cents": a.total_amount_cents,
            "biz_payload": a.biz_payload,
            "completed_at": a.completed_at,
        }
        for a in apps
    ]


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建/更新申请草稿或校验提交申请")
def save_or_submit_application(
    payload: ApplicationSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="当前账号尚未激活，无法提交申请")

    tpl = (
        db.query(models.WorkflowTemplate)
        .filter_by(code=payload.template_code, is_active=1)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=400, detail="所选审批流程模板不存在或已停用")

    if tpl.applicable_dept_ids and current_user.department_id not in tpl.applicable_dept_ids:
        raise HTTPException(status_code=403, detail="您所在的部门不在该流程模板的适用范围内")

    tpl_ver = (
        db.query(models.WorkflowTemplateVersion)
        .filter_by(template_id=tpl.id, version_num=tpl.current_version)
        .first()
    )
    if not tpl_ver:
        raise HTTPException(status_code=500, detail="流程模板版本配置缺失")

    is_submit = payload.action == "SUBMIT"

    # 若传入了 id，检查是否为本人处于 DRAFT 状态的草稿
    app_obj: Optional[models.Application] = None
    if payload.id:
        app_obj = db.query(models.Application).filter_by(id=payload.id).first()
        if not app_obj or app_obj.applicant_id != current_user.id:
            raise HTTPException(status_code=404, detail="草稿不存在或无权修改")
        if app_obj.status != "DRAFT":
            raise HTTPException(status_code=400, detail="只有处于【草稿】状态的申请才允许直接编辑修改")

    # 执行业务规则校验并由服务端计算精确总金额(分)
    total_cents, enriched_biz, has_risk = validate_and_calculate_business_rules(
        db=db,
        category=tpl.category,
        tpl_ver=tpl_ver,
        payload=payload,
        applicant=current_user,
        is_submit=is_submit,
        current_app_id=app_obj.id if app_obj else None,
    )

    now = datetime.now()
    if not app_obj:
        app_obj = models.Application(
            app_no=generate_unique_app_no(db, tpl.category),
            category=tpl.category,
            template_id=tpl.id,
            template_version_id=tpl_ver.id,
            title=payload.title.strip(),
            applicant_id=current_user.id,
            department_id=current_user.department_id,
            status="IN_REVIEW" if is_submit else "DRAFT",
            total_amount_cents=total_cents,
            current_node_seq=1 if is_submit else 0,
            ref_application_id=payload.ref_application_id,
            biz_payload=enriched_biz,
            has_risk_warning=has_risk,
            version=1,
            submitted_at=now if is_submit else None,
        )
        db.add(app_obj)
        db.flush()
    else:
        app_obj.template_id = tpl.id
        app_obj.template_version_id = tpl_ver.id
        app_obj.title = payload.title.strip()
        app_obj.department_id = current_user.department_id
        app_obj.status = "IN_REVIEW" if is_submit else "DRAFT"
        app_obj.total_amount_cents = total_cents
        app_obj.current_node_seq = 1 if is_submit else 0
        app_obj.ref_application_id = payload.ref_application_id
        app_obj.biz_payload = enriched_biz
        app_obj.has_risk_warning = has_risk
        app_obj.version += 1
        if is_submit:
            app_obj.submitted_at = now
        # 清理旧子表明细以便重建
        db.query(models.ProcurementItem).filter_by(application_id=app_obj.id).delete()
        db.query(models.ProcurementQuote).filter_by(application_id=app_obj.id).delete()
        db.query(models.ExpenseItem).filter_by(application_id=app_obj.id).delete()
        db.flush()

    # 写入采购明细与供应商比价
    if tpl.category == "PROCUREMENT":
        for item in payload.procurement_items:
            db.add(
                models.ProcurementItem(
                    application_id=app_obj.id,
                    item_name=item.item_name.strip(),
                    specification=item.specification.strip(),
                    quantity=item.quantity,
                    unit=item.unit.strip(),
                    unit_price_cents=item.unit_price_cents,
                    subtotal_cents=item.quantity * item.unit_price_cents,
                )
            )
        for quote in payload.procurement_quotes:
            db.add(
                models.ProcurementQuote(
                    application_id=app_obj.id,
                    supplier_name=quote.supplier_name.strip(),
                    quote_date=quote.quote_date,
                    quoted_amount_cents=quote.quoted_amount_cents,
                    purchase_url=quote.purchase_url,
                    is_selected=1 if quote.is_selected else 0,
                    attachment_id=quote.attachment_id,
                )
            )
            if quote.attachment_id:
                att = db.query(models.Attachment).filter_by(id=quote.attachment_id, uploaded_by=current_user.id).first()
                if att:
                    att.application_id = app_obj.id

    # 写入报销费用明细并绑定票据附件
    elif tpl.category == "EXPENSE":
        for exp in payload.expense_items:
            inv_nos = []
            exp_row = models.ExpenseItem(
                application_id=app_obj.id,
                expense_type=exp.expense_type,
                occur_date=exp.occur_date,
                description=exp.description.strip(),
                amount_cents=exp.amount_cents,
                is_no_invoice=1 if exp.is_no_invoice else 0,
                no_invoice_reason=exp.no_invoice_reason.strip() if exp.no_invoice_reason else None,
            )
            db.add(exp_row)
            db.flush()
            for att_id in exp.attachment_ids:
                att = db.query(models.Attachment).filter_by(id=att_id, uploaded_by=current_user.id).first()
                if att:
                    att.application_id = app_obj.id
                    att.expense_item_id = exp_row.id
                    if att.invoice_no:
                        inv_nos.append(att.invoice_no)
            exp_row.invoice_numbers = ",".join(inv_nos) if inv_nos else None

    # 绑定通用附件
    for att_id in payload.attachment_ids:
        att = db.query(models.Attachment).filter_by(id=att_id, uploaded_by=current_user.id).first()
        if att:
            att.application_id = app_obj.id

    # 若正式提交，解析并固化审批节点路径与人员快照
    if is_submit:
        db.query(models.ApprovalInstanceNode).filter_by(application_id=app_obj.id).delete()
        raw_nodes = sorted(tpl_ver.nodes_config or [], key=lambda x: x["node_seq"])
        active_nodes = [
            n for n in raw_nodes if total_cents >= int(n.get("min_amount_cents", 0))
        ]
        if not active_nodes:
            active_nodes = raw_nodes[:1]

        users_dict = {u.id: u.real_name for u in db.query(models.User).all()}
        snapshot_nodes = []
        first_approver_id: Optional[int] = None

        for seq_idx, n_cfg in enumerate(active_nodes, start=1):
            approver_id, delegated_from = resolve_node_approver(
                db, n_cfg["rule_type"], n_cfg.get("rule_value"), current_user
            )
            node_status = "PENDING" if seq_idx == 1 else "WAITING"
            if seq_idx == 1:
                first_approver_id = approver_id

            db.add(
                models.ApprovalInstanceNode(
                    application_id=app_obj.id,
                    node_seq=seq_idx,
                    node_name=n_cfg["node_name"],
                    rule_type=n_cfg["rule_type"],
                    approver_id=approver_id,
                    delegated_from_id=delegated_from,
                    status=node_status,
                )
            )
            snapshot_nodes.append(
                {
                    "node_seq": seq_idx,
                    "node_name": n_cfg["node_name"],
                    "rule_type": n_cfg["rule_type"],
                    "rule_value": n_cfg.get("rule_value"),
                    "min_amount_cents": n_cfg.get("min_amount_cents", 0),
                    "approver_id": approver_id,
                    "approver_name": users_dict.get(approver_id, ""),
                    "delegated_from_id": delegated_from,
                }
            )

        dept_obj = db.query(models.Department).filter_by(id=current_user.department_id).first()
        app_obj.snapshot_json = {
            "template_code": tpl.code,
            "template_name": tpl.name,
            "template_version": tpl_ver.version_num,
            "applicant_name": current_user.real_name,
            "department_name": dept_obj.name if dept_obj else "",
            "submitted_at": now.isoformat(),
            "form_schema": tpl_ver.form_schema,
            "resolved_nodes": snapshot_nodes,
        }

        # 记录提交日志与第一节点待办通知
        db.add(
            models.ApprovalLog(
                application_id=app_obj.id,
                template_version=tpl_ver.version_num,
                node_seq=0,
                node_name="申请人提交",
                operator_id=current_user.id,
                action="SUBMIT",
                comment="正式提交审批申请",
                result_status="IN_REVIEW",
                ip_address=request.client.host if request.client else None,
            )
        )
        if first_approver_id:
            create_notification_idempotent(
                db=db,
                recipient_id=first_approver_id,
                application_id=app_obj.id,
                notify_type="NEW_TODO",
                title=f"新审批待办：{app_obj.title}",
                content=f"员工 {current_user.real_name} 提交了《{app_obj.title}》({app_obj.app_no})，请您及时审批。",
                idempotency_key=f"app_{app_obj.id}_ver_{app_obj.version}_node_1_todo",
            )
    else:
        db.add(
            models.ApprovalLog(
                application_id=app_obj.id,
                template_version=tpl_ver.version_num,
                node_seq=0,
                node_name="保存草稿",
                operator_id=current_user.id,
                action="CREATE_DRAFT",
                comment="保存申请草稿",
                result_status="DRAFT",
                ip_address=request.client.host if request.client else None,
            )
        )

    db.commit()
    db.refresh(app_obj)
    return {
        "message": "申请已正式提交并进入审批流转" if is_submit else "草稿保存成功",
        "id": app_obj.id,
        "app_no": app_obj.app_no,
        "status": app_obj.status,
        "total_amount_cents": app_obj.total_amount_cents,
        "has_risk_warning": app_obj.has_risk_warning,
        "version": app_obj.version,
    }


@router.get("", summary="多视角分页查询申请列表(服务端强Data Scope权限过滤)")
def list_applications(
    view_mode: str = Query(
        "MY_APPLICATIONS",
        pattern="^(MY_APPLICATIONS|MY_TODOS|MY_DONE|DEPT_OVERVIEW|FINANCE_OVERVIEW|COMPANY_OVERVIEW)$",
    ),
    category: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    keyword: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user_roles = get_user_role_codes(db, current_user.id)
    query = db.query(models.Application)

    # 1. 根据 view_mode 执行严格的服务端数据范围(Data Scope)过滤
    if view_mode == "MY_APPLICATIONS":
        query = query.filter(models.Application.applicant_id == current_user.id)

    elif view_mode == "MY_TODOS":
        pending_app_ids = (
            db.query(models.ApprovalInstanceNode.application_id)
            .filter(
                models.ApprovalInstanceNode.approver_id == current_user.id,
                models.ApprovalInstanceNode.status == "PENDING",
            )
            .subquery()
        )
        query = query.filter(
            models.Application.status == "IN_REVIEW",
            models.Application.id.in_(pending_app_ids),
        )

    elif view_mode == "MY_DONE":
        done_app_ids = (
            db.query(models.ApprovalInstanceNode.application_id)
            .filter(
                models.ApprovalInstanceNode.approver_id == current_user.id,
                models.ApprovalInstanceNode.status.in_(["APPROVED", "REJECTED"]),
            )
            .subquery()
        )
        query = query.filter(models.Application.id.in_(done_app_ids))

    elif view_mode == "DEPT_OVERVIEW":
        if "DEPT_MANAGER" not in user_roles:
            raise HTTPException(status_code=403, detail="权限不足：仅部门负责人可查看本部门审批汇总")
        # 严格限制只能查看本部门非草稿申请，禁止跨部门查看
        query = query.filter(
            models.Application.department_id == current_user.department_id,
            models.Application.status != "DRAFT",
        )

    elif view_mode == "FINANCE_OVERVIEW":
        if "FINANCE" not in user_roles:
            raise HTTPException(status_code=403, detail="权限不足：仅财务审批人可查看授权财务单据")
        fin_node_app_ids = (
            db.query(models.ApprovalInstanceNode.application_id)
            .filter(models.ApprovalInstanceNode.approver_id == current_user.id)
            .subquery()
        )
        query = query.filter(
            models.Application.status != "DRAFT",
            or_(
                models.Application.id.in_(fin_node_app_ids),
                models.Application.category.in_(["PROCUREMENT", "EXPENSE"]),
            ),
        )

    elif view_mode == "COMPANY_OVERVIEW":
        if "EXECUTIVE" not in user_roles:
            raise HTTPException(status_code=403, detail="权限不足：仅获授权的企业负责人可查看全公司业务范围")
        query = query.filter(models.Application.status != "DRAFT")

    # 2. 筛选条件（类型、状态、时间、关键词）
    if category:
        query = query.filter(models.Application.category == category)
    if status_filter:
        query = query.filter(models.Application.status == status_filter)
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        query = query.filter(
            or_(models.Application.title.like(kw), models.Application.app_no.like(kw))
        )
    if start_date:
        query = query.filter(models.Application.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(models.Application.created_at <= datetime.combine(end_date, datetime.max.time()))

    total = query.count()
    items = (
        query.order_by(models.Application.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    users_map = {u.id: u.real_name for u in db.query(models.User).all()}
    depts_map = {d.id: d.name for d in db.query(models.Department).all()}

    result_list = []
    for a in items:
        cur_approver_name = None
        if a.status == "IN_REVIEW":
            cur_node = (
                db.query(models.ApprovalInstanceNode)
                .filter_by(application_id=a.id, status="PENDING")
                .first()
            )
            if cur_node:
                cur_approver_name = users_map.get(cur_node.approver_id, "")

        result_list.append(
            {
                "id": a.id,
                "app_no": a.app_no,
                "category": a.category,
                "title": a.title,
                "applicant_id": a.applicant_id,
                "applicant_name": users_map.get(a.applicant_id, ""),
                "department_id": a.department_id,
                "department_name": depts_map.get(a.department_id, ""),
                "status": a.status,
                "total_amount_cents": a.total_amount_cents,
                "current_node_seq": a.current_node_seq,
                "current_approver_name": cur_approver_name,
                "has_risk_warning": a.has_risk_warning,
                "version": a.version,
                "submitted_at": a.submitted_at,
                "completed_at": a.completed_at,
                "created_at": a.created_at,
            }
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result_list,
    }


def verify_application_detail_access(db: Session, current_user: models.User, app_obj: models.Application):
    """服务端校验当前用户是否有权查看该申请单详情"""
    if app_obj.applicant_id == current_user.id:
        return True

    if app_obj.status == "DRAFT":
        raise HTTPException(status_code=403, detail="越权访问拦截：他人草稿不可查看")

    is_node_member = (
        db.query(models.ApprovalInstanceNode)
        .filter(
            models.ApprovalInstanceNode.application_id == app_obj.id,
            or_(
                models.ApprovalInstanceNode.approver_id == current_user.id,
                models.ApprovalInstanceNode.delegated_from_id == current_user.id,
            ),
        )
        .first()
    )
    if is_node_member:
        return True

    user_roles = get_user_role_codes(db, current_user.id)
    if "DEPT_MANAGER" in user_roles and app_obj.department_id == current_user.department_id:
        return True
    if "FINANCE" in user_roles and app_obj.category in ("PROCUREMENT", "EXPENSE"):
        return True
    if "EXECUTIVE" in user_roles:
        return True

    raise HTTPException(
        status_code=403,
        detail="权限不足：服务端拒绝查看非本人、跨部门或未授权的申请详情（注意：系统管理员权限不等于业务查看权限）",
    )


@router.get("/{app_id}", summary="获取申请单完整详情、业务明细、当前审批人及历史留痕")
def get_application_detail(
    app_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    app_obj = db.query(models.Application).filter_by(id=app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="申请单不存在")

    verify_application_detail_access(db, current_user, app_obj)

    users_map = {u.id: u.real_name for u in db.query(models.User).all()}
    depts_map = {d.id: d.name for d in db.query(models.Department).all()}

    proc_items = db.query(models.ProcurementItem).filter_by(application_id=app_obj.id).all()
    proc_quotes = db.query(models.ProcurementQuote).filter_by(application_id=app_obj.id).all()
    exp_items = db.query(models.ExpenseItem).filter_by(application_id=app_obj.id).all()
    attachments = db.query(models.Attachment).filter_by(application_id=app_obj.id).all()
    nodes = (
        db.query(models.ApprovalInstanceNode)
        .filter_by(application_id=app_obj.id)
        .order_by(models.ApprovalInstanceNode.node_seq.asc())
        .all()
    )
    logs = (
        db.query(models.ApprovalLog)
        .filter_by(application_id=app_obj.id)
        .order_by(models.ApprovalLog.id.asc())
        .all()
    )

    ref_app_info = None
    if app_obj.ref_application_id:
        ref_a = db.query(models.Application).filter_by(id=app_obj.ref_application_id).first()
        if ref_a:
            ref_app_info = {
                "id": ref_a.id,
                "app_no": ref_a.app_no,
                "title": ref_a.title,
                "category": ref_a.category,
                "total_amount_cents": ref_a.total_amount_cents,
                "biz_payload": ref_a.biz_payload,
            }

    return {
        "id": app_obj.id,
        "app_no": app_obj.app_no,
        "category": app_obj.category,
        "template_id": app_obj.template_id,
        "template_version_id": app_obj.template_version_id,
        "title": app_obj.title,
        "applicant_id": app_obj.applicant_id,
        "applicant_name": users_map.get(app_obj.applicant_id, ""),
        "department_id": app_obj.department_id,
        "department_name": depts_map.get(app_obj.department_id, ""),
        "status": app_obj.status,
        "total_amount_cents": app_obj.total_amount_cents,
        "current_node_seq": app_obj.current_node_seq,
        "ref_application_id": app_obj.ref_application_id,
        "ref_application": ref_app_info,
        "copied_from_id": app_obj.copied_from_id,
        "biz_payload": app_obj.biz_payload,
        "snapshot_json": app_obj.snapshot_json,
        "has_risk_warning": app_obj.has_risk_warning,
        "version": app_obj.version,
        "submitted_at": app_obj.submitted_at,
        "completed_at": app_obj.completed_at,
        "created_at": app_obj.created_at,
        "procurement_items": [
            {
                "id": i.id,
                "item_name": i.item_name,
                "specification": i.specification,
                "quantity": i.quantity,
                "unit": i.unit,
                "unit_price_cents": i.unit_price_cents,
                "subtotal_cents": i.subtotal_cents,
            }
            for i in proc_items
        ],
        "procurement_quotes": [
            {
                "id": q.id,
                "supplier_name": q.supplier_name,
                "quote_date": q.quote_date,
                "quoted_amount_cents": q.quoted_amount_cents,
                "purchase_url": q.purchase_url,
                "is_selected": bool(q.is_selected),
                "attachment_id": q.attachment_id,
            }
            for q in proc_quotes
        ],
        "expense_items": [
            {
                "id": e.id,
                "expense_type": e.expense_type,
                "occur_date": e.occur_date,
                "description": e.description,
                "amount_cents": e.amount_cents,
                "is_no_invoice": bool(e.is_no_invoice),
                "no_invoice_reason": e.no_invoice_reason,
                "invoice_numbers": e.invoice_numbers,
            }
            for e in exp_items
        ],
        "attachments": [
            {
                "id": att.id,
                "expense_item_id": att.expense_item_id,
                "file_category": att.file_category,
                "original_name": att.original_name,
                "mime_type": att.mime_type,
                "file_size_bytes": att.file_size_bytes,
                "file_sha256": att.file_sha256,
                "invoice_no": att.invoice_no,
                "uploaded_by": att.uploaded_by,
                "uploaded_by_name": users_map.get(att.uploaded_by, ""),
                "uploaded_at": att.uploaded_at,
            }
            for att in attachments
        ],
        "nodes": [
            {
                "id": n.id,
                "node_seq": n.node_seq,
                "node_name": n.node_name,
                "rule_type": n.rule_type,
                "approver_id": n.approver_id,
                "approver_name": users_map.get(n.approver_id, ""),
                "delegated_from_id": n.delegated_from_id,
                "delegated_from_name": users_map.get(n.delegated_from_id, "") if n.delegated_from_id else None,
                "status": n.status,
                "comment": n.comment,
                "acted_at": n.acted_at,
            }
            for n in nodes
        ],
        "logs": [
            {
                "id": l.id,
                "node_seq": l.node_seq,
                "node_name": l.node_name,
                "operator_id": l.operator_id,
                "operator_name": users_map.get(l.operator_id, ""),
                "action": l.action,
                "comment": l.comment,
                "result_status": l.result_status,
                "created_at": l.created_at,
            }
            for l in logs
        ],
    }


@router.delete("/{app_id}", summary="申请人删除本人的草稿申请")
def delete_draft_application(
    app_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    app_obj = db.query(models.Application).filter_by(id=app_id).first()
    if not app_obj or app_obj.applicant_id != current_user.id:
        raise HTTPException(status_code=404, detail="申请不存在或无权删除")
    if app_obj.status != "DRAFT":
        raise HTTPException(status_code=400, detail="只能删除处于【草稿】状态的申请，已提交记录严禁删除")

    db.delete(app_obj)
    db.commit()
    return {"message": "草稿已删除"}