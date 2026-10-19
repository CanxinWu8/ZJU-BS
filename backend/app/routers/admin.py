from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app import models
from app.auth import require_roles, get_current_user, get_user_role_codes

router = APIRouter(prefix="/api/v1/admin", tags=["Admin & Workflow Templates"])

ALLOWED_FIELD_TYPES = {"text", "textarea", "number", "date", "radio", "file"}
ALLOWED_RULE_TYPES = {"DEPT_MANAGER", "ROLE", "USER"}


def record_admin_log(
    db: Session,
    operator_id: int,
    comment: str,
    result_status: str = "SUCCESS",
    ip_address: Optional[str] = None,
    template_version: Optional[int] = None,
):
    """记录管理员配置与授权变更留痕日志"""
    log = models.ApprovalLog(
        application_id=None,
        template_version=template_version,
        node_seq=None,
        node_name="SYSTEM_ADMIN",
        operator_id=operator_id,
        action="ADMIN_AUTH_CHANGE",
        comment=comment,
        result_status=result_status,
        ip_address=ip_address,
    )
    db.add(log)


# ==================== Schema 定义 ====================

class DepartmentSaveSchema(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=64)
    manager_user_id: Optional[int] = None
    is_active: int = Field(default=1)


class UserRoleAuthSchema(BaseModel):
    department_id: int
    status: str = Field(..., pattern="^(PENDING|ACTIVE|DISABLED)$")
    role_codes: List[str] = Field(..., min_length=1, description="赋予的角色编码列表，如 ['EMPLOYEE', 'FINANCE']")
    managed_dept_id: Optional[int] = Field(default=None, description="当赋予 DEPT_MANAGER 时关联管理的部门ID")


class FormFieldItemSchema(BaseModel):
    field_key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., description="支持: text, textarea, number, date, radio, file")
    required: bool = False
    options: Optional[List[str]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class NodeConfigItemSchema(BaseModel):
    node_seq: int = Field(..., ge=1)
    node_name: str = Field(..., min_length=1, max_length=64)
    rule_type: str = Field(..., description="支持: DEPT_MANAGER, ROLE, USER")
    rule_value: Optional[Any] = Field(default=None, description="ROLE时填角色编码如FINANCE，USER时填用户ID")
    min_amount_cents: int = Field(default=0, ge=0, description="触发该节点的最低金额阈值(分)")


class WorkflowTemplateSaveSchema(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=128)
    category: str = Field(default="CUSTOM", pattern="^(PROCUREMENT|TRAVEL|EXPENSE|CUSTOM)$")
    description: Optional[str] = ""
    applicable_dept_ids: Optional[List[int]] = None
    is_active: int = 1
    fields: List[FormFieldItemSchema] = Field(..., min_length=1)
    nodes_config: List[NodeConfigItemSchema] = Field(..., min_length=2, description="不少于两个顺序审批节点")


# ==================== 1. 部门与用户角色管理接口 ====================

@router.get("/departments", summary="管理员获取所有部门及负责人信息")
def admin_list_departments(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("ADMIN")),
):
    depts = db.query(models.Department).order_by(models.Department.id).all()
    users = {u.id: u.real_name for u in db.query(models.User).all()}
    return [
        {
            "id": d.id,
            "code": d.code,
            "name": d.name,
            "manager_user_id": d.manager_user_id,
            "manager_name": users.get(d.manager_user_id, "未指定"),
            "is_active": d.is_active,
        }
        for d in depts
    ]


@router.post("/departments", status_code=status.HTTP_201_CREATED, summary="新增或更新部门配置")
def admin_save_department(
    payload: DepartmentSaveSchema,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_roles("ADMIN")),
):
    dept = db.query(models.Department).filter_by(code=payload.code).first()
    action_desc = "更新部门" if dept else "创建新部门"
    if not dept:
        dept = models.Department(code=payload.code, name=payload.name)
        db.add(dept)
    else:
        dept.name = payload.name

    dept.manager_user_id = payload.manager_user_id
    dept.is_active = payload.is_active
    db.flush()

    record_admin_log(
        db,
        operator_id=admin_user.id,
        comment=f"{action_desc}: {dept.name}({dept.code}), 负责人ID={dept.manager_user_id}, 状态={dept.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": f"{action_desc}成功", "department_id": dept.id}


@router.get("/users", summary="获取全公司用户列表及角色归属")
def admin_list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("ADMIN")),
):
    users = db.query(models.User).order_by(models.User.id).all()
    depts = {d.id: d.name for d in db.query(models.Department).all()}
    result = []
    for u in users:
        roles = get_user_role_codes(db, u.id)
        result.append(
            {
                "id": u.id,
                "username": u.username,
                "real_name": u.real_name,
                "email": u.email,
                "department_id": u.department_id,
                "department_name": depts.get(u.department_id, ""),
                "status": u.status,
                "roles": roles,
                "created_at": u.created_at,
            }
        )
    return result


@router.put("/users/{user_id}/authorize", summary="管理员确认用户部门、状态并授予角色(留痕)")
def admin_authorize_user(
    user_id: int,
    payload: UserRoleAuthSchema,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_roles("ADMIN")),
):
    target_user = db.query(models.User).filter_by(id=user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    dept = db.query(models.Department).filter_by(id=payload.department_id).first()
    if not dept:
        raise HTTPException(status_code=400, detail="指定的部门不存在")

    all_roles = {r.code: r for r in db.query(models.Role).all()}
    for rc in payload.role_codes:
        if rc not in all_roles:
            raise HTTPException(status_code=400, detail=f"无效的角色编码: {rc}")

    old_roles = get_user_role_codes(db, target_user.id)
    old_dept_id = target_user.department_id
    old_status = target_user.status

    # 更新用户部门与状态
    target_user.department_id = payload.department_id
    target_user.status = payload.status

    # 重建角色绑定
    db.query(models.UserRole).filter_by(user_id=target_user.id).delete()
    for rc in payload.role_codes:
        managed_dept = (payload.managed_dept_id or payload.department_id) if rc == "DEPT_MANAGER" else None
        db.add(
            models.UserRole(
                user_id=target_user.id,
                role_id=all_roles[rc].id,
                managed_dept_id=managed_dept,
                granted_by=admin_user.id,
            )
        )
        # 若授予部门负责人角色，同步更新对应部门表的 manager_user_id
        if rc == "DEPT_MANAGER" and managed_dept:
            m_dept = db.query(models.Department).filter_by(id=managed_dept).first()
            if m_dept:
                m_dept.manager_user_id = target_user.id

    record_admin_log(
        db,
        operator_id=admin_user.id,
        comment=(
            f"变更用户[{target_user.username}/{target_user.real_name}]权限: "
            f"部门 {old_dept_id}->{payload.department_id}, "
            f"状态 {old_status}->{payload.status}, "
            f"角色 {old_roles}->{payload.role_codes}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "用户部门与角色权限已更新并记录审计日志", "roles": payload.role_codes}


# ==================== 2. 自定义流程模板与动态表单引擎接口 ====================

def validate_template_before_publish(db: Session, payload: WorkflowTemplateSaveSchema):
    """
    发布前严格校验（对应实验要求第6项）：
    1. 字段标识 field_key 唯一且字段类型合法
    2. 单选(radio)字段必须包含有效选项
    3. 节点不少于 2 个，顺序连续无环
    4. 每个节点的审批人规则有效且当前可解析到具体在职用户
    """
    # 1. 校验表单字段唯一性与规则
    seen_keys = set()
    for f in payload.fields:
        if f.type not in ALLOWED_FIELD_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的字段类型: {f.type}")
        if f.field_key in seen_keys:
            raise HTTPException(status_code=400, detail=f"表单字段标识重复: {f.field_key}")
        seen_keys.add(f.field_key)
        if f.type == "radio" and (not f.options or len(f.options) < 2):
            raise HTTPException(status_code=400, detail=f"单选字段 [{f.label}] 至少需要提供2个选项")

    # 2. 校验审批节点完整性、顺序与审批人规则可解析性
    if len(payload.nodes_config) < 2:
        raise HTTPException(status_code=400, detail="审批流程至少需要配置 2 个顺序审批节点")

    sorted_nodes = sorted(payload.nodes_config, key=lambda x: x.node_seq)
    expected_seqs = list(range(1, len(sorted_nodes) + 1))
    actual_seqs = [n.node_seq for n in sorted_nodes]
    if actual_seqs != expected_seqs:
        raise HTTPException(status_code=400, detail=f"节点序号必须从1开始严格递增无环，当前为: {actual_seqs}")

    for n in sorted_nodes:
        if n.rule_type not in ALLOWED_RULE_TYPES:
            raise HTTPException(status_code=400, detail=f"节点 [{n.node_name}] 审批人规则类型无效: {n.rule_type}")

        if n.rule_type == "USER":
            if not n.rule_value:
                raise HTTPException(status_code=400, detail=f"节点 [{n.node_name}] 未指定具体审批人ID")
            u = db.query(models.User).filter_by(id=int(n.rule_value), status="ACTIVE").first()
            if not u:
                raise HTTPException(status_code=400, detail=f"节点 [{n.node_name}] 指定的审批人不存在或未激活")

        elif n.rule_type == "ROLE":
            role = db.query(models.Role).filter_by(code=str(n.rule_value)).first()
            if not role:
                raise HTTPException(status_code=400, detail=f"节点 [{n.node_name}] 指定的角色 {n.rule_value} 不存在")
            holder_count = (
                db.query(models.UserRole)
                .join(models.User, models.User.id == models.UserRole.user_id)
                .filter(models.UserRole.role_id == role.id, models.User.status == "ACTIVE")
                .count()
            )
            if holder_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"节点 [{n.node_name}] 绑定的角色 [{n.rule_value}] 当前无任何有效在职用户，无法发布",
                )

        elif n.rule_type == "DEPT_MANAGER":
            active_depts_without_mgr = (
                db.query(models.Department)
                .filter(models.Department.is_active == 1, models.Department.manager_user_id.is_(None))
                .count()
            )
            if active_depts_without_mgr > 0:
                raise HTTPException(
                    status_code=400,
                    detail="存在启用中的部门尚未设置部门负责人，无法使用[申请人所在部门负责人]规则",
                )


@router.get("/templates", summary="获取审批流程模板列表(员工发起申请与管理员配置共用)")
def list_workflow_templates(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.WorkflowTemplate)
    user_roles = get_user_role_codes(db, current_user.id)
    if not (include_inactive and "ADMIN" in user_roles):
        query = query.filter(models.WorkflowTemplate.is_active == 1)

    templates = query.order_by(models.WorkflowTemplate.id).all()
    result = []
    for t in templates:
        # 若非管理员，过滤适用部门范围
        if "ADMIN" not in user_roles and t.applicable_dept_ids:
            if current_user.department_id not in t.applicable_dept_ids:
                continue

        latest_ver = (
            db.query(models.WorkflowTemplateVersion)
            .filter_by(template_id=t.id, version_num=t.current_version)
            .first()
        )
        result.append(
            {
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "category": t.category,
                "description": t.description,
                "applicable_dept_ids": t.applicable_dept_ids,
                "current_version": t.current_version,
                "template_version_id": latest_ver.id if latest_ver else None,
                "is_active": t.is_active,
                "form_schema": latest_ver.form_schema if latest_ver else {"fields": []},
                "nodes_config": latest_ver.nodes_config if latest_ver else [],
                "updated_at": t.updated_at,
            }
        )
    return result


@router.post("/templates", status_code=status.HTTP_201_CREATED, summary="管理员创建或发布新版本审批模板")
def save_or_publish_template(
    payload: WorkflowTemplateSaveSchema,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_roles("ADMIN")),
):
    # 1. 执行发布前静态校验
    validate_template_before_publish(db, payload)

    form_schema_dict = {"fields": [f.model_dump() for f in payload.fields]}
    nodes_list = [n.model_dump() for n in sorted(payload.nodes_config, key=lambda x: x.node_seq)]

    tpl = db.query(models.WorkflowTemplate).filter_by(code=payload.code).first()
    if not tpl:
        # 新建流程模板 (版本 v1)
        tpl = models.WorkflowTemplate(
            code=payload.code.strip().upper(),
            name=payload.name.strip(),
            category=payload.category,
            description=payload.description,
            applicable_dept_ids=payload.applicable_dept_ids,
            current_version=1,
            is_active=payload.is_active,
            created_by=admin_user.id,
        )
        db.add(tpl)
        db.flush()
        new_ver_num = 1
        action_text = "创建自定义流程模板"
    else:
        # 更新已有模板，自动递增版本号，保留历史版本与已有实例快照不受影响
        new_ver_num = tpl.current_version + 1
        tpl.name = payload.name.strip()
        tpl.description = payload.description
        tpl.applicable_dept_ids = payload.applicable_dept_ids
        tpl.current_version = new_ver_num
        tpl.is_active = payload.is_active
        action_text = "发布流程模板新版本"

    ver_record = models.WorkflowTemplateVersion(
        template_id=tpl.id,
        version_num=new_ver_num,
        form_schema=form_schema_dict,
        nodes_config=nodes_list,
        published_by=admin_user.id,
    )
    db.add(ver_record)
    db.flush()

    record_admin_log(
        db,
        operator_id=admin_user.id,
        template_version=new_ver_num,
        comment=f"{action_text}: [{tpl.name}({tpl.code})] v{new_ver_num}, 节点数={len(nodes_list)}, 字段数={len(payload.fields)}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return {
        "message": f"{action_text}成功 (当前版本 v{new_ver_num})",
        "template_id": tpl.id,
        "code": tpl.code,
        "version": new_ver_num,
        "template_version_id": ver_record.id,
    }


@router.patch("/templates/{template_id}/status", summary="启用或停用审批流程模板")
def toggle_template_status(
    template_id: int,
    is_active: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_roles("ADMIN")),
):
    tpl = db.query(models.WorkflowTemplate).filter_by(id=template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="流程模板不存在")

    tpl.is_active = 1 if is_active else 0
    record_admin_log(
        db,
        operator_id=admin_user.id,
        template_version=tpl.current_version,
        comment=f"切换流程模板 [{tpl.name}({tpl.code})] 状态为: {'启用' if tpl.is_active else '停用'}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "模板状态已更新", "template_id": tpl.id, "is_active": tpl.is_active}


@router.get("/audit-logs", summary="管理员查看系统权限与配置变更留痕日志")
def list_admin_audit_logs(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("ADMIN")),
):
    logs = (
        db.query(models.ApprovalLog)
        .filter(models.ApprovalLog.action == "ADMIN_AUTH_CHANGE")
        .order_by(models.ApprovalLog.id.desc())
        .limit(limit)
        .all()
    )
    users = {u.id: u.real_name for u in db.query(models.User).all()}
    return [
        {
            "id": l.id,
            "operator_id": l.operator_id,
            "operator_name": users.get(l.operator_id, "未知"),
            "action": l.action,
            "template_version": l.template_version,
            "comment": l.comment,
            "ip_address": l.ip_address,
            "created_at": l.created_at,
        }
        for l in logs
    ]