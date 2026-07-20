"""验证 LangGraph 诊断主链路能够完成场景、工具、检索和生成。"""

import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ac_py.agent.memory import MemoryManager
from ac_py.agent.workflow import AgentServices, create_workflow
from ac_py.config import Settings
from ac_py.tools.builtin import create_business_registry
from ac_py.tools.executor import ToolExecutor
from tests.fakes import FakeBusinessRepository, FakeModel, FakeSearcher, FakeStateStore


@pytest.mark.asyncio
async def test_workflow_completes_refund_diagnosis() -> None:
    """普通退款问题应完成诊断且不触发人工中断。"""

    store = FakeStateStore()
    registry = create_business_registry(FakeBusinessRepository())
    workflow = create_workflow(
        AgentServices(
            settings=Settings(llm_api_key="test", llm_model="test"),
            model=FakeModel(),
            searcher=FakeSearcher(),
            registry=registry,
            executor=ToolExecutor(registry, store),
            memory=MemoryManager(store, recent_turns=4, session_ttl_seconds=3600),
        ),
        InMemorySaver(),
    )
    result = await workflow.ainvoke(
        {
            "run_id": "run-1",
            "session_id": "session-1",
            "ticket_id": 1,
            "message": "退款审核通过了什么时候到账",
            "started_at": time.perf_counter(),
        },
        {"configurable": {"thread_id": "session-1"}},
    )
    assert result["scenes"] == ["refund"]
    assert result["answer"]
    assert result["evidence_report"].status.value == "ok"
