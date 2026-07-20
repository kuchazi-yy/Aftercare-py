"""验证场景分类、工具数量和高风险工具控制。"""

from ac_py.agent.routing import classify_scenes, parse_model_scene
from ac_py.domain.enums import Scene
from ac_py.domain.schemas import ToolCall
from ac_py.tools.builtin import create_business_registry
from ac_py.tools.executor import ToolExecutor
from tests.fakes import FakeBusinessRepository, FakeStateStore


def test_classify_multi_scene_message() -> None:
    """同时包含物流和退款诉求时应识别两个场景。"""

    scenes, confidence = classify_scenes("快递两天没更新，我还想申请退款")
    assert Scene.LOGISTICS in scenes
    assert Scene.REFUND in scenes
    assert confidence > 0.6


def test_parse_model_scene_requires_exact_label() -> None:
    """低置信度分类只接受精确场景标签，避免从解释文本中误判。"""

    assert parse_model_scene("refund") is Scene.REFUND
    assert parse_model_scene("我认为是 refund") is None


def test_registry_contains_fourteen_tools_and_filters_scene() -> None:
    """工具仓储应有 14 个工具，单场景最多暴露 7 个。"""

    registry = create_business_registry(FakeBusinessRepository())
    assert registry.count == 14
    refund_tools = registry.specs_for_scenes({Scene.REFUND})
    assert 6 <= len(refund_tools) <= 7
    assert "create_return_request" not in {tool.name for tool in refund_tools}


async def test_high_risk_tool_requires_approval_and_is_idempotent() -> None:
    """高风险工具未经批准不得写入，重复批准只执行一次。"""

    repository = FakeBusinessRepository()
    executor = ToolExecutor(create_business_registry(repository), FakeStateStore())
    call = ToolCall(
        name="create_refund_request",
        arguments={"ticket_id": 1, "reason": "用户申请退款"},
        idempotency_key="run-1:refund",
    )
    pending = await executor.execute(call, "run-1", {"refund:write"})
    assert pending.data["approval_required"] is True
    assert repository.records == []

    first = await executor.execute(call, "run-1", {"refund:write"}, approved=True)
    second = await executor.execute(call, "run-1", {"refund:write"}, approved=True)
    assert first.ok and second.ok
    assert len(repository.records) == 1
