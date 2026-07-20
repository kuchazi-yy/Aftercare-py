"""定义 Agent、检索、工具和 API 之间传递的稳定领域对象。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ac_py.domain.enums import EvidenceStatus, RiskLevel, Scene


class ConversationTurn(BaseModel):
    """表示会话中的一轮用户或助手消息。"""

    role: str
    content: str
    source_id: str | None = None


class BusinessContext(BaseModel):
    """汇总工具返回的最新业务事实，不承载模型推断。"""

    ticket: dict[str, Any] = Field(default_factory=dict)
    order: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    refund: dict[str, Any] = Field(default_factory=dict)
    return_request: dict[str, Any] = Field(default_factory=dict)
    logistics: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    quality_evidence: list[dict[str, Any]] = Field(default_factory=list)


class PolicyChunk(BaseModel):
    """表示可写入检索索引的政策父块或条款子块。"""

    chunk_id: str
    document_id: str
    version: str
    title: str
    parent_id: str | None = None
    level: str
    scene: Scene
    content: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    active: bool = True
    embedding: list[float] | None = None


class SearchHit(BaseModel):
    """表示融合与精排后的政策检索结果。"""

    chunk: PolicyChunk
    bm25_rank: int | None = None
    dense_rank: int | None = None
    rrf_score: float = 0
    rerank_score: float | None = None


class ToolManifest(BaseModel):
    """表示工具的轻量目录信息，供场景路由阶段使用。"""

    name: str
    description: str
    scenes: set[Scene]
    risk_level: RiskLevel


class ToolSpec(ToolManifest):
    """表示执行器需要的完整工具约束。"""

    input_schema: dict[str, Any]
    timeout_seconds: float = 3.0
    max_retries: int = 1
    idempotent: bool = True
    required_permission: str = "ticket:read"


class ToolCall(BaseModel):
    """表示模型或工作流请求执行的一次工具调用。"""

    name: str
    arguments: dict[str, Any]
    idempotency_key: str | None = None


class ToolResult(BaseModel):
    """表示规范化后的工具执行结果。"""

    name: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0
    cached: bool = False


class EvidenceReport(BaseModel):
    """表示业务事实与政策证据的校验结论。"""

    status: EvidenceStatus
    should_transfer: bool = False
    warnings: list[str] = Field(default_factory=list)


class DiagnosisOutput(BaseModel):
    """表示一次诊断对外返回的结构化结果。"""

    run_id: str
    scene: Scene
    summary: str
    answer: str
    evidence: list[SearchHit]
    evidence_report: EvidenceReport
    tools_used: list[str]
    first_progress_ms: int
    first_token_ms: int | None = None
    total_ms: int
