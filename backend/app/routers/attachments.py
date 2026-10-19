import hashlib
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app import models
from app.auth import get_current_user, get_user_role_codes

router = APIRouter(prefix="/api/v1/attachments", tags=["Attachments & Invoices"])

ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024  # 单文件上限 10MB
MAX_APP_FILES_COUNT = 20                  # 单申请单最多 20 个附件
MAX_APP_TOTAL_BYTES = 50 * 1024 * 1024    # 单申请单总附件上限 50MB


def check_duplicate_invoice(
    db: Session,
    file_sha256: str,
    invoice_no: Optional[str],
    exclude_app_id: Optional[int] = None,
):
    """
    检测跨申请单重复票据预警（基于文件 SHA-256 哈希或发票号码双重比对）
    """
    query = (
        db.query(models.Attachment, models.Application, models.User)
        .outerjoin(models.Application, models.Application.id == models.Attachment.application_id)
        .join(models.User, models.User.id == models.Attachment.uploaded_by)
    )
    if invoice_no and invoice_no.strip():
        clean_no = invoice_no.strip()
        query = query.filter(
            (models.Attachment.file_sha256 == file_sha256)
            | (models.Attachment.invoice_no == clean_no)
        )
    else:
        query = query.filter(models.Attachment.file_sha256 == file_sha256)

    if exclude_app_id is not None:
        query = query.filter(
            (models.Attachment.application_id != exclude_app_id)
            | (models.Attachment.application_id.is_(None))
        )

    warnings = []
    for att, app_obj, uploader in query.limit(5).all():
        # 忽略已撤回或已驳回作废的单据，仅对有效或未绑定单据预警
        if app_obj and app_obj.status in ("WITHDRAWN", "REJECTED"):
            continue
        warnings.append(
            {
                "matched_attachment_id": att.id,
                "matched_app_id": app_obj.id if app_obj else None,
                "matched_app_no": app_obj.app_no if app_obj else "草稿/未绑定申请单",
                "matched_app_status": app_obj.status if app_obj else "UNBOUND",
                "uploaded_by_name": uploader.real_name,
                "invoice_no": att.invoice_no,
                "reason": "发票号码一致" if (invoice_no and att.invoice_no == invoice_no.strip()) else "票据文件内容(SHA-256)完全一致",
                "uploaded_at": att.uploaded_at,
            }
        )
    return warnings


def verify_attachment_access(db: Session, current_user: models.User, att: models.Attachment):
    """
    服务端强制校验当前用户对该附件所属业务单的访问权限：
    1. 上传人本人或申请提交人本人 -> 允许
    2. 该申请单审批链路(approval_instance_nodes)中的历史/当前审批人 -> 允许
    3. 申请人所属部门的部门负责人 -> 允许
    4. 针对采购/报销单的财务审批人(FINANCE)或企业负责人(EXECUTIVE) -> 允许
    5. 其他无关员工、跨部门负责人、未经业务授权的单纯管理员 -> 严禁访问 (403)
    """
    if att.uploaded_by == current_user.id:
        return True

    if not att.application_id:
        raise HTTPException(status_code=403, detail="越权访问拦截：您无权查看其他用户尚未提交绑定的附件")

    app_obj = db.query(models.Application).filter_by(id=att.application_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="关联的申请单不存在")

    if app_obj.applicant_id == current_user.id:
        return True

    # 检查是否为本单的指定审批人或代理审批人
    is_node_approver = (
        db.query(models.ApprovalInstanceNode)
        .filter(
            models.ApprovalInstanceNode.application_id == app_obj.id,
            (models.ApprovalInstanceNode.approver_id == current_user.id)
            | (models.ApprovalInstanceNode.delegated_from_id == current_user.id),
        )
        .first()
    )
    if is_node_approver:
        return True

    user_roles = get_user_role_codes(db, current_user.id)

    # 部门负责人只能查看本部门的申请附件
    if "DEPT_MANAGER" in user_roles and app_obj.department_id == current_user.department_id:
        return True

    # 财务审批人可查看采购与报销类票据
    if "FINANCE" in user_roles and app_obj.category in ("PROCUREMENT", "EXPENSE"):
        return True

    # 企业负责人可查看全公司已提交业务附件
    if "EXECUTIVE" in user_roles and app_obj.status != "DRAFT":
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="权限不足：服务端拒绝访问非本人或非授权范围的业务票据附件",
    )


@router.post("/upload", status_code=status.HTTP_201_CREATED, summary="上传业务附件或报销票据(含SHA256防重检测)")
async def upload_attachment(
    file: UploadFile = File(...),
    file_category: str = Form("INVOICE", description="QUOTE_PROOF, TRAVEL_DOC, INVOICE, CUSTOM_ATTACHMENT"),
    invoice_no: Optional[str] = Form(None, description="选填：发票号码"),
    application_id: Optional[int] = Form(None, description="选填：关联的申请单ID"),
    expense_item_id: Optional[int] = Form(None, description="选填：关联的报销明细ID"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if file_category not in ("QUOTE_PROOF", "TRAVEL_DOC", "INVOICE", "CUSTOM_ATTACHMENT"):
        raise HTTPException(status_code=400, detail="无效的附件分类")

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式({file.content_type})，仅支持 JPEG、PNG、PDF",
        )

    content = await file.read()
    file_size = len(content)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="不能上传空文件")
    if file_size > MAX_SINGLE_FILE_BYTES:
        raise HTTPException(status_code=400, detail="单文件大小不能超过 10MB")

    # 若指定了 application_id，校验归属及单据附件总数量/总大小上限
    if application_id is not None:
        app_obj = db.query(models.Application).filter_by(id=application_id).first()
        if not app_obj or app_obj.applicant_id != current_user.id:
            raise HTTPException(status_code=403, detail="只能向本人的申请单上传附件")
        existing_atts = db.query(models.Attachment).filter_by(application_id=application_id).all()
        if len(existing_atts) >= MAX_APP_FILES_COUNT:
            raise HTTPException(status_code=400, detail=f"单张申请最多允许上传 {MAX_APP_FILES_COUNT} 个附件")
        total_bytes = sum(a.file_size_bytes for a in existing_atts) + file_size
        if total_bytes > MAX_APP_TOTAL_BYTES:
            raise HTTPException(status_code=400, detail="单张申请附件总大小不能超过 50MB")

    # 计算 SHA-256 哈希
    file_sha256 = hashlib.sha256(content).hexdigest()

    # 检测跨申请重复票据预警
    duplicate_warnings = check_duplicate_invoice(db, file_sha256, invoice_no, exclude_app_id=application_id)

    # 写入受控存储目录
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = ALLOWED_MIME_TYPES[file.content_type]
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    full_path = upload_dir / stored_filename
    full_path.write_bytes(content)

    att = models.Attachment(
        application_id=application_id,
        expense_item_id=expense_item_id,
        file_category=file_category,
        original_name=file.filename or stored_filename,
        storage_path=stored_filename,
        mime_type=file.content_type,
        file_size_bytes=file_size,
        file_sha256=file_sha256,
        invoice_no=invoice_no.strip() if invoice_no else None,
        uploaded_by=current_user.id,
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    return {
        "id": att.id,
        "original_name": att.original_name,
        "mime_type": att.mime_type,
        "file_size_bytes": att.file_size_bytes,
        "file_sha256": att.file_sha256,
        "invoice_no": att.invoice_no,
        "uploaded_by": att.uploaded_by,
        "uploaded_at": att.uploaded_at,
        "has_duplicate_warning": len(duplicate_warnings) > 0,
        "duplicate_warnings": duplicate_warnings,
    }


@router.get("/{attachment_id}/file", summary="受控附件鉴权预览或下载")
def get_attachment_file(
    attachment_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    att = db.query(models.Attachment).filter_by(id=attachment_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="附件不存在")

    # 服务端强权限检查
    verify_attachment_access(db, current_user, att)

    file_path = Path(settings.UPLOAD_DIR) / att.storage_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="物理文件已丢失")

    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=str(file_path),
        media_type=att.mime_type,
        filename=att.original_name if download else None,
        headers={"Content-Disposition": f'{disposition}; filename="{att.original_name}"'},
    )