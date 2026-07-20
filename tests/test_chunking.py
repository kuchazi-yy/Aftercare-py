"""验证政策父子切分和原子文档策略。"""

from ac_py.domain.enums import Scene
from ac_py.rag.chunking import split_policy


def test_short_policy_is_atomic() -> None:
    """短政策应保持完整，避免无意义碎片化。"""

    chunks = split_policy("doc", "v1", "短政策", "退款审核通过后原路退回。", Scene.REFUND)
    assert len(chunks) == 1
    assert chunks[0].level == "atomic"


def test_long_policy_builds_parent_and_children() -> None:
    """长政策应按标题形成父章节和受长度限制的子块。"""

    text = "# 退款时效\n" + "审核通过后原路退回。" * 80 + "\n# 退款异常\n" + "超过时效转人工。" * 20
    chunks = split_policy("doc", "v1", "退款政策", text, Scene.REFUND, max_chars=180)
    parents = [chunk for chunk in chunks if chunk.level == "parent"]
    children = [chunk for chunk in chunks if chunk.level == "child"]
    assert len(parents) == 2
    assert children
    assert all(chunk.parent_id for chunk in children)
    assert all(len(chunk.content) <= 180 for chunk in children)
