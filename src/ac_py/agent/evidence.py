"""校验政策召回、业务状态和用户诉求之间是否存在缺失或冲突。"""

from ac_py.domain.enums import EvidenceStatus, Scene
from ac_py.domain.schemas import BusinessContext, EvidenceReport, SearchHit


def validate_evidence(
    scenes: list[Scene],
    context: BusinessContext,
    evidence: list[SearchHit],
) -> EvidenceReport:
    """依据确定性规则给出证据状态和转人工建议。"""

    warnings: list[str] = []
    if not evidence:
        return EvidenceReport(
            status=EvidenceStatus.INSUFFICIENT,
            should_transfer=True,
            warnings=["未检索到适用政策"],
        )
    if not context.order:
        warnings.append("未查询到关联订单")
    if Scene.REFUND in scenes:
        order_status = str(context.order.get("status", ""))
        refund_status = str(context.refund.get("status", ""))
        if order_status == "refunded" and refund_status in {"failed", "rejected"}:
            warnings.append("订单与退款状态冲突")
    if Scene.LOGISTICS in scenes and not context.logistics:
        warnings.append("缺少物流轨迹")
    if warnings:
        status = (
            EvidenceStatus.CONFLICT
            if any("冲突" in item for item in warnings)
            else EvidenceStatus.INSUFFICIENT
        )
        return EvidenceReport(status=status, should_transfer=True, warnings=warnings)
    return EvidenceReport(status=EvidenceStatus.OK)


def build_diagnosis_summary(
    scenes: list[Scene],
    context: BusinessContext,
    evidence: list[SearchHit],
    report: EvidenceReport,
) -> str:
    """在模型生成前构造可立即返回的结构化诊断摘要。"""

    scene_text = ",".join(scene.value for scene in scenes)
    order_status = context.order.get("status", "unknown")
    references = ",".join(hit.chunk.chunk_id for hit in evidence[:3]) or "none"
    return (
        f"场景={scene_text}; 订单状态={order_status}; "
        f"证据状态={report.status.value}; 政策引用={references}"
    )
