"""定义 LangGraph 在各诊断节点之间传递的可持久化状态。"""

from typing import Any, TypedDict

from ac_py.domain.schemas import (
    BusinessContext,
    ConversationTurn,
    EvidenceReport,
    SearchHit,
    ToolResult,
)


class DiagnosisState(TypedDict, total=False):
    """描述一次诊断执行的完整状态快照。"""

    run_id: str
    session_id: str
    ticket_id: int
    message: str
    normalized_message: str
    scenes: list[str]
    scene_confidence: float
    memory_summary: str
    recent_turns: list[ConversationTurn]
    selected_tools: list[str]
    tool_results: list[ToolResult]
    business_context: BusinessContext
    search_query: str
    evidence: list[SearchHit]
    evidence_report: EvidenceReport
    diagnosis_summary: str
    prompt_messages: list[dict[str, str]]
    answer: str
    tools_used: list[str]
    requested_action: dict[str, Any] | None
    approval_decision: dict[str, Any] | None
    should_transfer: bool
    first_token_ms: int | None
    started_at: float
