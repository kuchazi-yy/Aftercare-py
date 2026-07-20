"""定义业务事实、知识库、Agent 运行、Memory、评测和审计数据表。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ac_py.db.base import Base


def utc_now() -> datetime:
    """返回不带时区的 UTC 时间，统一数据库时间口径。"""

    return datetime.utcnow()


class TimestampMixin:
    """为需要审计时间的数据表提供创建与更新时间。"""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class User(Base, TimestampMixin):
    """保存系统用户身份。"""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Role(Base, TimestampMixin):
    """保存角色及其权限集合。"""

    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)


class UserRole(Base):
    """关联用户与角色。"""

    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)


class Customer(Base, TimestampMixin):
    """保存售后业务中的客户主体。"""

    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class Product(Base, TimestampMixin):
    """保存商品及其售后分类信息。"""

    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64), default="general")


class Order(Base, TimestampMixin):
    """保存订单事实并作为退款、物流和工单的关联入口。"""

    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    status: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = mapped_column(Integer)


class Refund(Base, TimestampMixin):
    """保存退款申请及其当前状态。"""

    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(256), default="")
    amount: Mapped[int] = mapped_column(Integer)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ReturnRequest(Base, TimestampMixin):
    """保存退货申请、资格和进度。"""

    __tablename__ = "return_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(256), default="")


class Logistics(Base, TimestampMixin):
    """保存订单物流轨迹和异常状态。"""

    __tablename__ = "logistics"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    tracking_no: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Ticket(Base, TimestampMixin):
    """保存售后工单及其诊断状态。"""

    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(32), default="open")
    description: Mapped[str] = mapped_column(Text)
    scene: Mapped[str | None] = mapped_column(String(32), nullable=True)


class TicketRecord(Base, TimestampMixin):
    """保存工单状态变化与人工处理记录。"""

    __tablename__ = "ticket_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    operator: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, default="")


class PolicyDocument(Base, TimestampMixin):
    """保存政策文档的稳定身份和来源信息。"""

    __tablename__ = "policy_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    source_uri: Mapped[str] = mapped_column(String(512), default="")


class PolicyVersion(Base, TimestampMixin):
    """保存政策版本、正文和索引发布状态。"""

    __tablename__ = "policy_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("policy_documents.id"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    scene: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    __table_args__ = (Index("ix_policy_version_unique", "document_id", "version", unique=True),)


class PolicySection(Base, TimestampMixin):
    """保存文档解析后的父章节与条款子块。"""

    __tablename__ = "policy_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True)
    parent_chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)


class IndexJob(Base, TimestampMixin):
    """保存政策解析、向量化和索引发布任务。"""

    __tablename__ = "index_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id"))
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DiagnosisSession(Base, TimestampMixin):
    """保存一个工单范围内的多轮诊断会话。"""

    __tablename__ = "diagnosis_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))


class DiagnosisRun(Base, TimestampMixin):
    """保存一次 LangGraph 诊断执行及其性能数据。"""

    __tablename__ = "diagnosis_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_sessions.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    scene: Mapped[str] = mapped_column(String(32))
    first_progress_ms: Mapped[int] = mapped_column(Integer, default=0)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolCallLog(Base, TimestampMixin):
    """保存工具调用参数、结果、风险和性能数据。"""

    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int] = mapped_column(Integer)


class DiagnosisResult(Base, TimestampMixin):
    """保存最终结构化诊断和客服回复。"""

    __tablename__ = "diagnosis_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), unique=True)
    summary: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    evidence_status: Mapped[str] = mapped_column(String(32))
    should_transfer: Mapped[bool] = mapped_column(Boolean, default=False)


class EvidenceCitation(Base, TimestampMixin):
    """保存诊断回复引用的政策证据。"""

    __tablename__ = "evidence_citations"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(128))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)


class ApprovalRequest(Base, TimestampMixin):
    """保存需要人工审批的高风险动作。"""

    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), index=True)
    action: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    decision_note: Mapped[str] = mapped_column(Text, default="")


class MemorySummary(Base, TimestampMixin):
    """保存工单会话压缩后的长期摘要。"""

    __tablename__ = "memory_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    source_record_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class Feedback(Base, TimestampMixin):
    """保存客服对诊断结果的采纳、修改和失败反馈。"""

    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")


class EvalDataset(Base, TimestampMixin):
    """保存版本化评测集。"""

    __tablename__ = "eval_datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    version: Mapped[str] = mapped_column(String(64))


class EvalCase(Base, TimestampMixin):
    """保存单条评测输入、期望结果和标签。"""

    __tablename__ = "eval_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("eval_datasets.id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    expected: Mapped[dict[str, Any]] = mapped_column(JSON)


class EvalRun(Base, TimestampMixin):
    """保存一次评测实验配置与汇总状态。"""

    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("eval_datasets.id"))
    experiment: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))


class EvalResult(Base, TimestampMixin):
    """保存评测样例级结果和指标。"""

    __tablename__ = "eval_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id"), index=True)
    eval_case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id"))
    output: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditLog(Base, TimestampMixin):
    """保存权限、审批和后台操作的永久审计记录。"""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(128))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
