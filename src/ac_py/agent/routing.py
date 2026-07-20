"""实现无需模型调用的售后场景分类、工具选择和检索 Query 构造。"""

import re
from typing import Any

from ac_py.domain.enums import Scene
from ac_py.domain.schemas import BusinessContext, ToolCall

SCENE_TERMS: dict[Scene, tuple[str, ...]] = {
    Scene.REFUND: (
        "退款",
        "退钱",
        "退到",
        "到账",
        "钱没到",
        "refund",
    ),
    Scene.RETURN: (
        "退货",
        "换货",
        "退换",
        "返修",
        "维修",
        "寄回",
        "运费",
        "受理点",
        "return",
        "exchange",
    ),
    Scene.LOGISTICS: (
        "物流",
        "快递",
        "配送",
        "派送",
        "送到",
        "签收",
        "站点",
        "没动静",
        "未收到",
        "丢件",
        "tracking",
        "courier",
    ),
    Scene.QUALITY: (
        "质量",
        "破损",
        "坏了",
        "损坏",
        "少件",
        "少配件",
        "漏发",
        "瑕疵",
        "包装",
        "broken",
        "missing",
    ),
}

SCENE_READ_TOOLS: dict[Scene, tuple[str, ...]] = {
    Scene.REFUND: ("get_refund", "get_refund_timeline"),
    Scene.RETURN: ("get_return_request", "check_return_eligibility"),
    Scene.LOGISTICS: ("get_logistics_track", "check_delivery_exception"),
    Scene.QUALITY: ("get_product", "get_quality_evidence"),
    Scene.OTHER: (),
}

SCENE_LABELS = {scene.value: scene for scene in Scene if scene is not Scene.OTHER}


def normalize_message(message: str) -> str:
    """压缩用户输入中的空白并限制异常长输入。"""

    return re.sub(r"\s+", " ", message).strip()[:8000]


def classify_scenes(
    message: str,
    context: str = "",
    max_scenes: int = 2,
) -> tuple[list[Scene], float]:
    """结合当前问题和最近上下文识别最多两个场景。"""

    lowered = message.lower()
    context_lowered = context.lower()
    scored = [
        (
            scene,
            2 * sum(1 for term in terms if term in lowered)
            + sum(1 for term in terms if term in context_lowered),
        )
        for scene, terms in SCENE_TERMS.items()
    ]
    matched = [(scene, score) for scene, score in scored if score > 0]
    if not matched:
        return [Scene.OTHER], 0.35
    matched.sort(key=lambda item: item[1], reverse=True)
    selected = [scene for scene, _ in matched[:max_scenes]]
    confidence = min(0.98, 0.65 + 0.1 * sum(score for _, score in matched[:max_scenes]))
    return selected, confidence


def parse_model_scene(content: str) -> Scene | None:
    """从低置信度分类模型的短回复中解析单个场景标签。"""

    normalized = content.strip().lower()
    for label, scene in SCENE_LABELS.items():
        if normalized == label or scene.name.lower() == normalized:
            return scene
    return None


def build_tool_calls(ticket_id: int, scenes: list[Scene]) -> list[ToolCall]:
    """为当前场景创建通用及场景读工具调用，写工具不进入自动查询链路。"""

    names = ["get_ticket", "get_order", "get_ticket_history"]
    for scene in scenes:
        names.extend(SCENE_READ_TOOLS[scene])
    unique_names = list(dict.fromkeys(names))[:9]
    return [ToolCall(name=name, arguments={"ticket_id": ticket_id}) for name in unique_names]


def build_search_query(message: str, scenes: list[Scene], context: BusinessContext) -> str:
    """把用户问题、场景和少量最新业务状态组合为紧凑检索 Query。"""

    labels = " ".join(scene.value for scene in scenes)
    status_parts = [
        str(context.order.get("status", "")),
        str(context.refund.get("status", "")),
        str(context.logistics.get("status", "")),
        str(context.return_request.get("status", "")),
    ]
    statuses = " ".join(part for part in status_parts if part)
    return f"{labels} {statuses} {message}".strip()


def requested_high_risk_action(
    message: str, scenes: list[Scene], ticket_id: int
) -> dict[str, Any] | None:
    """识别用户是否要求直接执行退款或退货等高风险动作。"""

    if Scene.REFUND in scenes and any(
        term in message for term in ("直接退款", "帮我退款", "立即退款")
    ):
        return {
            "name": "create_refund_request",
            "arguments": {"ticket_id": ticket_id, "reason": message},
        }
    if Scene.RETURN in scenes and any(
        term in message for term in ("直接退货", "申请退货", "立即退货")
    ):
        return {
            "name": "create_return_request",
            "arguments": {"ticket_id": ticket_id, "reason": message},
        }
    return None
