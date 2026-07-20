"""按照证据优先级和硬 Token 预算构造最终模型上下文。"""

import json

import tiktoken

from ac_py.domain.schemas import BusinessContext, ConversationTurn, EvidenceReport, SearchHit

SYSTEM_PROMPT = """你是电商售后客服辅助系统。只能依据最新业务事实和明确引用的政策条款回答。
不得自行承诺退款、赔付或退货；证据不足、状态冲突或政策不适用时必须建议人工复核。
回复应简洁，先说明判断，再列依据和下一步，不输出内部推理过程。"""


def count_tokens(text: str) -> int:
    """使用通用编码估算文本 Token 数，编码不可用时使用字符近似。"""

    try:
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 2)


def trim_to_tokens(text: str, token_limit: int) -> str:
    """按 Token 上限裁剪文本并保留开头的高优先级内容。"""

    if count_tokens(text) <= token_limit:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if count_tokens(text[:middle]) <= token_limit:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def build_prompt_messages(
    message: str,
    context: BusinessContext,
    evidence: list[SearchHit],
    report: EvidenceReport,
    memory_summary: str,
    recent_turns: list[ConversationTurn],
    token_budget: int,
) -> list[dict[str, str]]:
    """按业务事实、Top3 证据、摘要和最近对话的优先级构造 Prompt。"""

    business_text = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, default=str)
    evidence_text = "\n".join(
        f"[{index}] 政策{hit.chunk.document_id} 版本{hit.chunk.version} "
        f"标题:{hit.chunk.title} 内容:{hit.chunk.content[:900]}"
        for index, hit in enumerate(evidence[:3], start=1)
    )
    history_text = "\n".join(f"{turn.role}: {turn.content}" for turn in recent_turns)
    sections = [
        ("最新业务事实", business_text, 1600),
        ("政策证据", evidence_text or "未检索到适用政策", 2200),
        ("历史摘要", memory_summary or "无", 700),
        ("最近对话", history_text or "无", 900),
    ]
    reserved = count_tokens(SYSTEM_PROMPT) + count_tokens(message) + 300
    remaining = max(500, token_budget - reserved)
    rendered: list[str] = []
    for title, content, preferred in sections:
        allowance = min(preferred, remaining)
        if allowance <= 0:
            break
        value = trim_to_tokens(content, allowance)
        rendered.append(f"## {title}\n{value}")
        remaining -= count_tokens(value)
    user_prompt = (
        f"用户问题：{message}\n"
        f"证据状态：{report.status.value}\n"
        f"风险提示：{'；'.join(report.warnings) or '无'}\n\n"
        + "\n\n".join(rendered)
        + "\n\n请输出可直接提供给客服使用的回复，总字数不超过200字，并使用[1][2]形式引用政策证据。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
