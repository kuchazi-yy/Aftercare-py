"""装配 LangGraph 诊断状态图，并实现可流式输出和人工中断的各节点。"""

import time
from dataclasses import dataclass
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

from ac_py.agent.evidence import build_diagnosis_summary, validate_evidence
from ac_py.agent.memory import MemoryManager
from ac_py.agent.prompt import build_prompt_messages
from ac_py.agent.routing import (
    build_search_query,
    build_tool_calls,
    classify_scenes,
    normalize_message,
    parse_model_scene,
    requested_high_risk_action,
)
from ac_py.agent.state import DiagnosisState
from ac_py.config import Settings
from ac_py.db.repositories import DiagnosisRepository
from ac_py.domain.enums import Scene
from ac_py.domain.schemas import BusinessContext, ToolCall
from ac_py.llm.client import ModelClient
from ac_py.rag.search import PolicySearcher
from ac_py.tools.executor import ToolExecutor
from ac_py.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentServices:
    """集中声明 LangGraph 节点依赖，避免节点直接使用全局变量。"""

    settings: Settings
    model: ModelClient
    searcher: PolicySearcher
    registry: ToolRegistry
    executor: ToolExecutor
    memory: MemoryManager
    diagnosis_repository: DiagnosisRepository | None = None


def create_workflow(services: AgentServices, checkpointer: Any = None) -> Any:
    """创建并编译售后诊断状态图。"""

    builder = StateGraph(DiagnosisState)

    async def normalize_node(state: DiagnosisState) -> dict[str, Any]:
        """标准化用户输入并发出工作流开始事件。"""

        writer = get_stream_writer()
        writer({"event": "normalize", "data": "问题已接收"})
        return {"normalized_message": normalize_message(state["message"])}

    async def memory_node(state: DiagnosisState) -> dict[str, Any]:
        """加载会话摘要和最近四轮消息。"""

        summary, turns = await services.memory.load(state["session_id"])
        return {"memory_summary": summary, "recent_turns": turns}

    async def route_node(state: DiagnosisState) -> dict[str, Any]:
        """使用规则识别场景并判断是否包含高风险动作。"""

        context = "\n".join(
            [state.get("memory_summary", "")]
            + [turn.content for turn in state.get("recent_turns", [])]
        )
        scenes, confidence = classify_scenes(state["normalized_message"], context)
        if confidence < 0.6:
            tokens = [
                token
                async for token in services.model.stream_chat(
                    [
                        {
                            "role": "system",
                            "content": "只输出 refund、return、logistics、quality 之一。",
                        },
                        {
                            "role": "user",
                            "content": (
                                f"最近对话：{context[-1200:]}\n"
                                f"当前问题：{state['normalized_message']}"
                            ),
                        },
                    ],
                    12,
                )
            ]
            model_scene = parse_model_scene("".join(tokens))
            if model_scene is not None:
                scenes, confidence = [model_scene], 0.8
        writer = get_stream_writer()
        writer({"event": "scene", "data": [scene.value for scene in scenes]})
        return {
            "scenes": [scene.value for scene in scenes],
            "scene_confidence": confidence,
            "requested_action": requested_high_risk_action(
                state["normalized_message"], scenes, state["ticket_id"]
            ),
        }

    async def tools_node(state: DiagnosisState) -> dict[str, Any]:
        """按场景筛选工具并并发查询最新业务事实。"""

        scenes = [Scene(value) for value in state["scenes"]]
        specs = services.registry.specs_for_scenes(set(scenes))
        visible = {spec.name for spec in specs}
        calls = [
            call for call in build_tool_calls(state["ticket_id"], scenes) if call.name in visible
        ]
        permissions = {
            "ticket:read",
            "ticket:transfer",
            "refund:write",
            "return:write",
        }
        results = await services.executor.execute_many(calls, state["run_id"], permissions)
        context = _context_from_results(results)
        writer = get_stream_writer()
        writer({"event": "tools", "data": [result.name for result in results]})
        return {
            "selected_tools": [spec.name for spec in specs],
            "tool_results": results,
            "business_context": context,
            "tools_used": [result.name for result in results if result.ok],
        }

    async def query_node(state: DiagnosisState) -> dict[str, Any]:
        """根据最新业务事实生成紧凑政策检索 Query。"""

        scenes = [Scene(value) for value in state["scenes"]]
        query = build_search_query(
            state["normalized_message"],
            scenes,
            state["business_context"],
        )
        return {"search_query": query}

    async def search_node(state: DiagnosisState) -> dict[str, Any]:
        """调用 Elasticsearch 混合检索并返回精排 Top3。"""

        primary_scene = Scene(state["scenes"][0])
        hits = await services.searcher.search(state["search_query"], primary_scene)
        writer = get_stream_writer()
        writer({"event": "retrieval", "data": {"count": len(hits)}})
        return {"evidence": hits}

    async def evidence_node(state: DiagnosisState) -> dict[str, Any]:
        """校验业务事实和政策证据，并生成可立即展示的摘要。"""

        scenes = [Scene(value) for value in state["scenes"]]
        report = validate_evidence(scenes, state["business_context"], state["evidence"])
        summary = build_diagnosis_summary(
            scenes,
            state["business_context"],
            state["evidence"],
            report,
        )
        writer = get_stream_writer()
        writer({"event": "diagnosis_summary", "data": summary})
        return {
            "evidence_report": report,
            "diagnosis_summary": summary,
            "should_transfer": report.should_transfer,
        }

    async def approval_node(state: DiagnosisState) -> dict[str, Any]:
        """对高风险业务动作暂停工作流并等待人工决定。"""

        action = state.get("requested_action")
        if action is None:
            return {}
        decision = interrupt(
            {
                "run_id": state["run_id"],
                "action": action,
                "diagnosis_summary": state["diagnosis_summary"],
            }
        )
        approved = isinstance(decision, dict) and decision.get("decision") == "approve"
        if approved:
            edited = decision.get("edited_payload") if isinstance(decision, dict) else None
            arguments = edited if isinstance(edited, dict) else action["arguments"]
            call = ToolCall(
                name=action["name"],
                arguments=arguments,
                idempotency_key=f"{state['run_id']}:{action['name']}",
            )
            result = await services.executor.execute(
                call,
                state["run_id"],
                {"refund:write", "return:write"},
                approved=True,
            )
            return {
                "approval_decision": decision,
                "tool_results": [*state.get("tool_results", []), result],
                "tools_used": [*state.get("tools_used", []), result.name],
                "should_transfer": state.get("should_transfer", False) or not result.ok,
            }
        return {
            "approval_decision": decision,
            "should_transfer": True,
        }

    async def prompt_node(state: DiagnosisState) -> dict[str, Any]:
        """按 6000 Token 硬预算组装最终模型输入。"""

        messages = build_prompt_messages(
            state["normalized_message"],
            state["business_context"],
            state["evidence"],
            state["evidence_report"],
            state.get("memory_summary", ""),
            state.get("recent_turns", []),
            services.settings.prompt_token_budget,
        )
        return {"prompt_messages": messages}

    async def generate_node(state: DiagnosisState) -> dict[str, Any]:
        """执行唯一一次主要模型调用并流式转发 Token。"""

        writer = get_stream_writer()
        answer_parts: list[str] = []
        first_token_ms: int | None = None
        async for token in services.model.stream_chat(
            state["prompt_messages"],
            services.settings.output_token_limit,
        ):
            if first_token_ms is None:
                first_token_ms = int((time.perf_counter() - state["started_at"]) * 1000)
            answer_parts.append(token)
            writer({"event": "message", "data": token})
        if not answer_parts:
            raise RuntimeError("模型未返回正文")
        return {"answer": "".join(answer_parts), "first_token_ms": first_token_ms}

    async def persist_node(state: DiagnosisState) -> dict[str, Any]:
        """保存会话消息和最终诊断结果。"""

        await services.memory.append(state["session_id"], "user", state["normalized_message"])
        await services.memory.append(state["session_id"], "assistant", state["answer"])
        total_ms = int((time.perf_counter() - state["started_at"]) * 1000)
        if services.diagnosis_repository is not None:
            await services.diagnosis_repository.complete_run(
                state["run_id"],
                state["diagnosis_summary"],
                state["answer"],
                state["evidence_report"].status.value,
                state.get("should_transfer", False),
                0,
                state.get("first_token_ms"),
                total_ms,
                state["evidence"],
            )
        writer = get_stream_writer()
        writer({"event": "done", "data": {"total_ms": total_ms}})
        await services.memory.compact(state["session_id"])
        return {}

    builder.add_node("normalize", normalize_node)
    builder.add_node("load_memory", memory_node)
    builder.add_node("route_scene", route_node)
    builder.add_node("query_tools", tools_node, retry_policy=RetryPolicy(max_attempts=2))
    builder.add_node("build_query", query_node)
    builder.add_node("search_policy", search_node, retry_policy=RetryPolicy(max_attempts=2))
    builder.add_node("check_evidence", evidence_node)
    builder.add_node("approval", approval_node)
    builder.add_node("build_prompt", prompt_node)
    builder.add_node("generate", generate_node)
    builder.add_node("persist", persist_node)
    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "load_memory")
    builder.add_edge("load_memory", "route_scene")
    builder.add_edge("route_scene", "query_tools")
    builder.add_edge("query_tools", "build_query")
    builder.add_edge("build_query", "search_policy")
    builder.add_edge("search_policy", "check_evidence")
    builder.add_edge("check_evidence", "approval")
    builder.add_edge("approval", "build_prompt")
    builder.add_edge("build_prompt", "generate")
    builder.add_edge("generate", "persist")
    builder.add_edge("persist", END)
    return builder.compile(checkpointer=checkpointer)


def _context_from_results(results: list[Any]) -> BusinessContext:
    """把工具结果映射为结构化业务上下文。"""

    context = BusinessContext()
    for result in results:
        if not result.ok:
            continue
        payload = result.data.get("data", result.data)
        if result.name == "get_ticket":
            context.ticket = payload
        elif result.name == "get_order":
            context.order = payload
        elif result.name == "get_ticket_history":
            context.history = payload
        elif result.name == "get_refund":
            context.refund = payload
        elif result.name == "get_return_request":
            context.return_request = payload
        elif result.name == "get_logistics_track":
            context.logistics = payload
        elif result.name == "get_product":
            context.product = payload
        elif result.name == "get_quality_evidence":
            context.quality_evidence = payload
    return context
