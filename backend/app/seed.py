from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.auth import hash_password

DEFAULT_PWD = "Zju123456"


def run_seed(db: Session):
    # 1. 初始化部门（研发部、市场部、财务部、总经办）
    depts_data = [
        ("DEPT_RND", "研发部"),
        ("DEPT_MKT", "市场部"),
        ("DEPT_FIN", "财务部"),
        ("DEPT_EXEC", "总经办"),
    ]
    dept_map = {}
    for code, name in depts_data:
        dept = db.query(models.Department).filter_by(code=code).first()
        if not dept:
            dept = models.Department(code=code, name=name, is_active=1)
            db.add(dept)
            db.flush()
        dept_map[code] = dept

    # 2. 初始化五类标准角色
    roles_data = [
        ("EMPLOYEE", "普通员工", "SELF"),
        ("DEPT_MANAGER", "部门负责人", "DEPT"),
        ("FINANCE", "财务审批人", "AUTHORIZED_BIZ"),
        ("EXECUTIVE", "企业负责人", "COMPANY"),
        ("ADMIN", "系统管理员", "SELF"),
    ]
    role_map = {}
    for code, name, scope in roles_data:
        role = db.query(models.Role).filter_by(code=code).first()
        if not role:
            role = models.Role(code=code, name=name, default_data_scope=scope)
            db.add(role)
            db.flush()
        role_map[code] = role

    # 3. 初始化预设演示用户（密码统一为 Zju123456）
    pwd_hash = hash_password(DEFAULT_PWD)
    users_data = [
        ("admin", "系统管理员", "admin@zju.edu.cn", "DEPT_EXEC", ["ADMIN"]),
        ("emp_rnd", "员工 1(研发员工)", "emp1@zju.edu.cn", "DEPT_RND", ["EMPLOYEE"]),
        ("emp_mkt", "员工 2(市场员工)", "emp2@zju.edu.cn", "DEPT_MKT", ["EMPLOYEE"]),
        ("mgr_rnd", "经理 1(研发经理)", "mgr1@zju.edu.cn", "DEPT_RND", ["EMPLOYEE", "DEPT_MANAGER"]),
        ("mgr_mkt", "经理 2(市场经理)", "mgr2@zju.edu.cn", "DEPT_MKT", ["EMPLOYEE", "DEPT_MANAGER"]),
        ("fin_auditor", "经理 3(财务经理)", "mgr3@zju.edu.cn", "DEPT_FIN", ["EMPLOYEE", "DEPT_MANAGER", "FINANCE"]),
        ("ceo", "总管(企业负责人)", "ceo@zju.edu.cn", "DEPT_EXEC", ["EMPLOYEE", "DEPT_MANAGER", "EXECUTIVE"]),
    ]
    user_map = {}
    for username, real_name, email, dept_code, role_codes in users_data:
        user = db.query(models.User).filter_by(username=username).first()
        if not user:
            user = models.User(
                username=username,
                real_name=real_name,
                email=email,
                password_hash=pwd_hash,
                department_id=dept_map[dept_code].id,
                status="ACTIVE",
            )
            db.add(user)
            db.flush()
        user_map[username] = user

        # 绑定角色
        for r_code in role_codes:
            r_obj = role_map[r_code]
            managed_dept = dept_map[dept_code].id if r_code == "DEPT_MANAGER" else None
            exists_ur = (
                db.query(models.UserRole)
                .filter_by(user_id=user.id, role_id=r_obj.id, managed_dept_id=managed_dept)
                .first()
            )
            if not exists_ur:
                db.add(
                    models.UserRole(
                        user_id=user.id,
                        role_id=r_obj.id,
                        managed_dept_id=managed_dept,
                        granted_by=user_map["admin"].id,
                    )
                )

    # 4. 设置各部门负责人
    dept_map["DEPT_RND"].manager_user_id = user_map["mgr_rnd"].id
    dept_map["DEPT_MKT"].manager_user_id = user_map["mgr_mkt"].id
    dept_map["DEPT_FIN"].manager_user_id = user_map["fin_auditor"].id
    dept_map["DEPT_EXEC"].manager_user_id = user_map["ceo"].id
    db.flush()

    # 5. 初始化三大固定流程模板 + 第四类自定义流程模板（请假审批）
    templates_init = [
        {
            "code": "PROCUREMENT_STD",
            "name": "标准采购审批流程",
            "category": "PROCUREMENT",
            "description": "适用于企业软硬件、办公物资及服务采购，支持多明细与供应商比价。",
            "form_schema": {
                "fields": [
                    {"field_key": "reason", "label": "采购原因", "type": "textarea", "required": True},
                    {"field_key": "expected_date", "label": "期望到货日期", "type": "date", "required": True},
                    {"field_key": "project_name", "label": "所属项目/专项", "type": "text", "required": False},
                    {"field_key": "budget_limit_cents", "label": "预算上限(分)", "type": "number", "required": True},
                ]
            },
            "nodes_config": [
                {"node_seq": 1, "node_name": "部门负责人审批", "rule_type": "DEPT_MANAGER", "rule_value": None, "min_amount_cents": 0},
                {"node_seq": 2, "node_name": "财务预算审查", "rule_type": "ROLE", "rule_value": "FINANCE", "min_amount_cents": 0},
                {"node_seq": 3, "node_name": "企业负责人终审(满5000元)", "rule_type": "ROLE", "rule_value": "EXECUTIVE", "min_amount_cents": 500000},
            ],
        },
        {
            "code": "TRAVEL_STD",
            "name": "员工差旅申请流程",
            "category": "TRAVEL",
            "description": "出差前提交行程与预算申请，获批后可作为报销前置关联单据。",
            "form_schema": {
                "fields": [
                    {"field_key": "departure", "label": "出发地点", "type": "text", "required": True},
                    {"field_key": "destination", "label": "目的地点", "type": "text", "required": True},
                    {"field_key": "start_date", "label": "开始日期", "type": "date", "required": True},
                    {"field_key": "end_date", "label": "结束日期", "type": "date", "required": True},
                    {"field_key": "transport", "label": "交通方式", "type": "radio", "options": ["高铁", "飞机", "大巴/自驾", "其他"], "required": True},
                    {"field_key": "purpose", "label": "出差目的", "type": "textarea", "required": True},
                ]
            },
            "nodes_config": [
                {"node_seq": 1, "node_name": "部门负责人审批", "rule_type": "DEPT_MANAGER", "rule_value": None, "min_amount_cents": 0},
                {"node_seq": 2, "node_name": "企业负责人审批(预算满3000元)", "rule_type": "ROLE", "rule_value": "EXECUTIVE", "min_amount_cents": 300000},
            ],
        },
        {
            "code": "EXPENSE_STD",
            "name": "费用报销审批流程",
            "category": "EXPENSE",
            "description": "支持关联差旅/采购单或独立日常报销，含发票防重与无票异常核查。",
            "form_schema": {
                "fields": [
                    {"field_key": "expense_desc", "label": "报销事由说明", "type": "textarea", "required": True},
                    {"field_key": "remark", "label": "补充备注", "type": "text", "required": False},
                ]
            },
            "nodes_config": [
                {"node_seq": 1, "node_name": "部门负责人审核", "rule_type": "DEPT_MANAGER", "rule_value": None, "min_amount_cents": 0},
                {"node_seq": 2, "node_name": "财务票据与合规审核", "rule_type": "ROLE", "rule_value": "FINANCE", "min_amount_cents": 0},
                {"node_seq": 3, "node_name": "企业负责人终审(满5000元)", "rule_type": "ROLE", "rule_value": "EXECUTIVE", "min_amount_cents": 500000},
            ],
        },
        {
            "code": "CUSTOM_LEAVE",
            "name": "员工请假与外出审批(自定义流程)",
            "category": "CUSTOM",
            "description": "管理员通过动态表单引擎配置的第四类自定义审批流程示例。",
            "form_schema": {
                "fields": [
                    {"field_key": "leave_type", "label": "请假类型", "type": "radio", "options": ["年假", "事假", "病假", "调休"], "required": True},
                    {"field_key": "start_date", "label": "开始日期", "type": "date", "required": True},
                    {"field_key": "leave_days", "label": "请假天数", "type": "number", "required": True},
                    {"field_key": "handover_person", "label": "工作交接人", "type": "text", "required": True},
                    {"field_key": "leave_reason", "label": "请假具体原因", "type": "textarea", "required": True},
                    {"field_key": "proof_file", "label": "相关证明附件", "type": "file", "required": False},
                ]
            },
            "nodes_config": [
                {"node_seq": 1, "node_name": "所属部门负责人审批", "rule_type": "DEPT_MANAGER", "rule_value": None, "min_amount_cents": 0},
                {"node_seq": 2, "node_name": "总经办备案终审", "rule_type": "USER", "rule_value": user_map["ceo"].id, "min_amount_cents": 0},
            ],
        },
    ]

    admin_id = user_map["admin"].id
    for tpl_item in templates_init:
        tpl = db.query(models.WorkflowTemplate).filter_by(code=tpl_item["code"]).first()
        if not tpl:
            tpl = models.WorkflowTemplate(
                code=tpl_item["code"],
                name=tpl_item["name"],
                category=tpl_item["category"],
                description=tpl_item["description"],
                applicable_dept_ids=None,
                current_version=1,
                is_active=1,
                created_by=admin_id,
            )
            db.add(tpl)
            db.flush()

            ver = models.WorkflowTemplateVersion(
                template_id=tpl.id,
                version_num=1,
                form_schema=tpl_item["form_schema"],
                nodes_config=tpl_item["nodes_config"],
                published_by=admin_id,
            )
            db.add(ver)

    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        run_seed(session)
        print("Seed data initialized successfully!")