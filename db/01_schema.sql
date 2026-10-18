-- 文件路径: db/01_schema.sql
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

USE approval_system;

-- 1. 部门表[cite: 1]
CREATE TABLE IF NOT EXISTS departments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(32) NOT NULL UNIQUE COMMENT '部门编码: DEPT_RND, DEPT_MKT, DEPT_FIN, DEPT_EXEC',
    name VARCHAR(64) NOT NULL COMMENT '部门名称',
    manager_user_id BIGINT NULL COMMENT '当前部门负责人ID',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 用户表[cite: 1]
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE COMMENT '唯一登录用户名',
    real_name VARCHAR(64) NOT NULL COMMENT '真实姓名',
    email VARCHAR(128) NOT NULL UNIQUE COMMENT '唯一邮箱',
    password_hash VARCHAR(255) NOT NULL COMMENT 'BCrypt加密哈希(密码>=8位)',
    department_id BIGINT NOT NULL COMMENT '所属部门ID',
    status ENUM('PENDING', 'ACTIVE', 'DISABLED') NOT NULL DEFAULT 'PENDING' COMMENT '默认待确认状态',
    webpush_sub_json JSON NULL COMMENT 'WebPush订阅凭证',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_dept FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 角色表与用户角色关联表[cite: 1]
CREATE TABLE IF NOT EXISTS roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(32) NOT NULL UNIQUE COMMENT 'EMPLOYEE, DEPT_MANAGER, FINANCE, EXECUTIVE, ADMIN',
    name VARCHAR(64) NOT NULL,
    default_data_scope ENUM('SELF', 'DEPT', 'AUTHORIZED_BIZ', 'COMPANY') NOT NULL DEFAULT 'SELF'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    managed_dept_id BIGINT NULL COMMENT '兼任部门负责人时绑定的部门ID',
    granted_by BIGINT NULL COMMENT '授权管理员ID',
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_role_dept (user_id, role_id, managed_dept_id),
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 流程模板与版本表[cite: 1]
CREATE TABLE IF NOT EXISTS workflow_templates (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(64) NOT NULL UNIQUE COMMENT 'PROCURE, TRAVEL, EXPENSE 或自定义编码',
    name VARCHAR(128) NOT NULL,
    category ENUM('PROCUREMENT', 'TRAVEL', 'EXPENSE', 'CUSTOM') NOT NULL,
    description VARCHAR(500) NULL,
    applicable_dept_ids JSON NULL COMMENT '适用部门ID列表，NULL为全公司',
    current_version INT NOT NULL DEFAULT 1,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_by BIGINT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workflow_template_versions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_id BIGINT NOT NULL,
    version_num INT NOT NULL,
    form_schema JSON NOT NULL COMMENT '动态表单字段定义与校验规则',
    nodes_config JSON NOT NULL COMMENT '顺序审批节点、条件阈值及审批人解析规则',
    published_by BIGINT NOT NULL,
    published_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_tpl_ver (template_id, version_num),
    CONSTRAINT fk_ver_tpl FOREIGN KEY (template_id) REFERENCES workflow_templates(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 申请主表[cite: 1]
CREATE TABLE IF NOT EXISTS applications (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    app_no VARCHAR(40) NOT NULL UNIQUE COMMENT '唯一编号',
    category ENUM('PROCUREMENT', 'TRAVEL', 'EXPENSE', 'CUSTOM') NOT NULL,
    template_id BIGINT NOT NULL,
    template_version_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL,
    applicant_id BIGINT NOT NULL,
    department_id BIGINT NOT NULL COMMENT '提交时所属部门快照',
    status ENUM('DRAFT', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'WITHDRAWN') NOT NULL DEFAULT 'DRAFT',
    total_amount_cents BIGINT NOT NULL DEFAULT 0 COMMENT '精确总金额(单位:分)',
    current_node_seq INT NOT NULL DEFAULT 0,
    ref_application_id BIGINT NULL COMMENT '报销关联的已批准差旅/采购单ID',
    copied_from_id BIGINT NULL COMMENT '重新提交关联的原申请ID',
    biz_payload JSON NOT NULL COMMENT '业务扩展字段与自定义表单数据',
    snapshot_json JSON NULL COMMENT '提交时固化的审批路径与人员快照',
    has_risk_warning TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否触发无票异常或重复票据预警',
    version INT NOT NULL DEFAULT 1 COMMENT '乐观锁版本号',
    submitted_at DATETIME NULL,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_applicant_status (applicant_id, status),
    INDEX idx_dept_status_time (department_id, status, submitted_at),
    CONSTRAINT fk_app_applicant FOREIGN KEY (applicant_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_app_tpl_ver FOREIGN KEY (template_version_id) REFERENCES workflow_template_versions(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 采购明细与供应商报价表[cite: 1]
CREATE TABLE IF NOT EXISTS procurement_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    item_name VARCHAR(128) NOT NULL,
    specification VARCHAR(128) NOT NULL,
    quantity INT NOT NULL,
    unit VARCHAR(32) NOT NULL,
    unit_price_cents BIGINT NOT NULL,
    subtotal_cents BIGINT NOT NULL,
    CONSTRAINT fk_proc_item_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS procurement_quotes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    supplier_name VARCHAR(128) NOT NULL,
    quote_date DATE NOT NULL,
    quoted_amount_cents BIGINT NOT NULL,
    purchase_url VARCHAR(500) NULL,
    is_selected TINYINT(1) NOT NULL DEFAULT 0,
    attachment_id BIGINT NULL,
    CONSTRAINT fk_proc_quote_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 报销费用明细表[cite: 1]
CREATE TABLE IF NOT EXISTS expense_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    expense_type VARCHAR(32) NOT NULL COMMENT 'TRAFFIC, HOTEL, MEAL, OFFICE, OTHER',
    occur_date DATE NOT NULL,
    description VARCHAR(255) NOT NULL,
    amount_cents BIGINT NOT NULL,
    is_no_invoice TINYINT(1) NOT NULL DEFAULT 0,
    no_invoice_reason VARCHAR(255) NULL,
    invoice_numbers VARCHAR(255) NULL,
    CONSTRAINT fk_exp_item_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. 流程实例审批节点表[cite: 1]
CREATE TABLE IF NOT EXISTS approval_instance_nodes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    node_seq INT NOT NULL,
    node_name VARCHAR(64) NOT NULL,
    rule_type VARCHAR(32) NOT NULL,
    approver_id BIGINT NOT NULL,
    delegated_from_id BIGINT NULL,
    status ENUM('WAITING', 'PENDING', 'APPROVED', 'REJECTED', 'SKIPPED', 'CANCELED') NOT NULL DEFAULT 'WAITING',
    comment TEXT NULL,
    acted_at DATETIME NULL,
    UNIQUE KEY uk_app_node_seq (application_id, node_seq),
    INDEX idx_approver_pending (approver_id, status),
    CONSTRAINT fk_node_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 审批与管理留痕日志表[cite: 1]
CREATE TABLE IF NOT EXISTS approval_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NULL,
    template_version INT NULL,
    node_seq INT NULL,
    node_name VARCHAR(64) NULL,
    operator_id BIGINT NOT NULL,
    action ENUM('CREATE_DRAFT', 'SUBMIT', 'APPROVE', 'REJECT', 'WITHDRAW', 'RESUBMIT', 'URGE', 'DELEGATE', 'ADMIN_AUTH_CHANGE') NOT NULL,
    comment TEXT NULL,
    result_status VARCHAR(32) NOT NULL,
    ip_address VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_log_app (application_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. 附件与票据资料表[cite: 1]
CREATE TABLE IF NOT EXISTS attachments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NULL COMMENT '上传时可暂为NULL，保存草稿或提交时绑定',
    expense_item_id BIGINT NULL,
    file_category ENUM('QUOTE_PROOF', 'TRAVEL_DOC', 'INVOICE', 'CUSTOM_ATTACHMENT') NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    mime_type VARCHAR(64) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    invoice_no VARCHAR(64) NULL,
    uploaded_by BIGINT NOT NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sha256 (file_sha256),
    INDEX idx_invoice_no (invoice_no),
    CONSTRAINT fk_att_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 11. 持久化站内通知表[cite: 1]
CREATE TABLE IF NOT EXISTS notifications (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    recipient_id BIGINT NOT NULL,
    application_id BIGINT NULL,
    notify_type ENUM('NEW_TODO', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'URGE_REMINDER') NOT NULL,
    title VARCHAR(200) NOT NULL,
    content VARCHAR(500) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    read_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recipient_unread (recipient_id, is_read, created_at),
    CONSTRAINT fk_notif_user FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 12. 审批委托规则表(增强功能)[cite: 1]
CREATE TABLE IF NOT EXISTS approval_delegations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    delegator_id BIGINT NOT NULL COMMENT '原审批人ID',
    delegatee_id BIGINT NOT NULL COMMENT '代理人ID',
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    reason VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_del_from FOREIGN KEY (delegator_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_del_to FOREIGN KEY (delegatee_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;