"""验证 Prompt 预算和 Top3 证据限制。"""

from ac_py.agent.prompt import build_prompt_messages, count_tokens
from ac_py.domain.enums import EvidenceStatus, Scene
from ac_py.domain.schemas import BusinessContext, EvidenceReport, PolicyChunk, SearchHit


def test_prompt_respects_budget_and_top_three() -> None:
    """最终 Prompt 不应超过预算太多，也不应注入第四条证据。"""

    hits = [
        SearchHit(
            chunk=PolicyChunk(
                chunk_id=f"chunk-{index}",
                document_id="refund",
                version="v1",
                title=f"政策{index}",
                level="child",
                scene=Scene.REFUND,
                content="退款条款。" * 200,
            )
        )
        for index in range(4)
    ]
    messages = build_prompt_messages(
        "退款什么时候到账",
        BusinessContext(order={"status": "paid"}),
        hits,
        EvidenceReport(status=EvidenceStatus.OK),
        "",
        [],
        3000,
    )
    combined = "\n".join(message["content"] for message in messages)
    assert "政策2" in combined
    assert "政策3" not in combined
    assert count_tokens(combined) <= 3100
