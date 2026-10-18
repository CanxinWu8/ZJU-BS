from datetime import datetime, date
from typing import Optional, Any
from sqlalchemy import (
    BigInteger, String, Integer, Text, DateTime, Date,
    ForeignKey, JSON, CHAR, func
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    manager_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    real_name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("departments.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    webpush_sub_json: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    default_data_scope: Mapped[str] = mapped_column(String(32), default="SELF", nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id"), nullable=False)
    managed_dept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    granted_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    applicable_dept_ids: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class WorkflowTemplateVersion(Base):
    __tablename__ = "workflow_template_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workflow_templates.id"), nullable=False)
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    form_schema: Mapped[Any] = mapped_column(JSON, nullable=False)
    nodes_config: Mapped[Any] = mapped_column(JSON, nullable=False)
    published_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    app_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    template_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    template_version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workflow_template_versions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    applicant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    total_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    current_node_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ref_application_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    copied_from_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    biz_payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    snapshot_json: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    has_risk_warning: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProcurementItem(Base):
    __tablename__ = "procurement_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("applications.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(128), nullable=False)
    specification: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ProcurementQuote(Base):
    __tablename__ = "procurement_quotes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("applications.id"), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(128), nullable=False)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    quoted_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purchase_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_selected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attachment_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class ExpenseItem(Base):
    __tablename__ = "expense_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("applications.id"), nullable=False)
    expense_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occur_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_no_invoice: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    no_invoice_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_numbers: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class ApprovalInstanceNode(Base):
    __tablename__ = "approval_instance_nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("applications.id"), nullable=False)
    node_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    approver_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delegated_from_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="WAITING", nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ApprovalLog(Base):
    __tablename__ = "approval_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    template_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    node_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    node_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("applications.id"), nullable=True)
    expense_item_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    file_category: Mapped[str] = mapped_column(String(32), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    application_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    notify_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ApprovalDelegation(Base):
    __tablename__ = "approval_delegations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    delegator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    delegatee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())