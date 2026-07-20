"""实现工单、诊断、审批、政策、工具、健康和监控接口。"""

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from langfuse import observe
from langgraph.types import Command
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.responses import Response

from ac_py.api.schemas import (
    CreateTicketRequest,
    DiagnoseRequest,
    PolicyIndexRequest,
    ResumeRequest,
    SearchDebugRequest,
    UpdateTicketStatusRequest,
)
from ac_py.observability.metrics import SSE_CONNECTIONS
from ac_py.runtime import Runtime
from ac_py.tasks.jobs import index_policy_version

router = APIRouter()


def runtime(request: Request) -> Runtime:
    """从当前请求获取共享运行时。"""

    return cast(Runtime, request.app.state.runtime)


def graph_input(payload: DiagnoseRequest, run_id: str, session_id: str) -> dict[str, Any]:
    """把 HTTP 诊断请求转换为 LangGraph 初始状态。"""

    return {
        "run_id": run_id,
        "session_id": session_id,
        "ticket_id": payload.ticket_id,
        "message": payload.message,
        "started_at": time.perf_counter(),
    }


def graph_config(session_id: str) -> dict[str, dict[str, str]]:
    """生成 LangGraph Checkpoint 使用的线程配置。"""

    return {"configurable": {"thread_id": session_id}}


@observe(name="aftercare-diagnosis")
async def invoke_graph(rt: Runtime, state: dict[str, Any], session_id: str) -> dict[str, Any]:
    """执行一次非流式 LangGraph 诊断并纳入 Langfuse Trace。"""

    return cast(dict[str, Any], await rt.graph.ainvoke(state, graph_config(session_id)))


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """检查 MySQL、Redis 和 Elasticsearch 连接。"""

    rt = runtime(request)
    dependencies: dict[str, str] = {}
    try:
        async with rt.database.engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")
        dependencies["mysql"] = "ok"
    except Exception:  # noqa: BLE001
        dependencies["mysql"] = "error"
    dependencies["redis"] = "ok" if await rt.state_store.ping() else "error"
    dependencies["elasticsearch"] = "ok" if await rt.elasticsearch.ping() else "error"
    status = "ok" if all(value == "ok" for value in dependencies.values()) else "degraded"
    return {"status": status, "dependencies": dependencies}


@router.post("/tickets")
async def create_ticket(payload: CreateTicketRequest, request: Request) -> dict[str, Any]:
    """创建售后工单。"""

    try:
        ticket = await runtime(request).business_repository.create_ticket(
            payload.order_no,
            payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": ticket}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int, request: Request) -> dict[str, Any]:
    """查询工单及最近处理记录。"""

    rt = runtime(request)
    ticket = await rt.business_repository.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return {
        "data": {
            "ticket": ticket,
            "records": await rt.business_repository.get_history(ticket_id),
        }
    }


@router.patch("/tickets/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: int,
    payload: UpdateTicketStatusRequest,
    request: Request,
) -> dict[str, Any]:
    """更新工单状态并主动失效相关短期缓存。"""

    rt = runtime(request)
    try:
        ticket = await rt.business_repository.update_ticket_status(
            ticket_id,
            payload.status,
            payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tool_keys = [f"tool:{name}:ticket:{ticket_id}" for name in rt.registry.names]
    await rt.state_store.delete(*tool_keys)
    return {"data": ticket}


@router.post("/diagnoses")
async def diagnose(payload: DiagnoseRequest, request: Request) -> dict[str, Any]:
    """执行非流式诊断，适合接口测试和批量评测。"""

    rt = runtime(request)
    run_id = uuid.uuid4().hex
    session_id = payload.session_id or f"ticket-{payload.ticket_id}"
    await rt.diagnosis_repository.start_run(session_id, run_id, payload.ticket_id, "pending")
    try:
        result = await invoke_graph(rt, graph_input(payload, run_id, session_id), session_id)
    except Exception as exc:
        await rt.diagnosis_repository.fail_run(run_id, str(exc))
        raise
    if result.get("__interrupt__"):
        return {
            "status": "waiting_approval",
            "run_id": run_id,
            "interrupt": result["__interrupt__"],
        }
    return {"data": result}


@router.post("/diagnoses/stream")
async def stream_diagnose(payload: DiagnoseRequest, request: Request) -> EventSourceResponse:
    """通过 SSE 返回诊断阶段、结构化摘要和模型 Token。"""

    rt = runtime(request)
    run_id = uuid.uuid4().hex
    session_id = payload.session_id or f"ticket-{payload.ticket_id}"

    async def events() -> AsyncIterator[ServerSentEvent]:
        """按 LangGraph 自定义事件生成 SSE 数据。"""

        SSE_CONNECTIONS.inc()
        started = time.perf_counter()
        try:
            yield ServerSentEvent(
                event="accepted",
                data=json.dumps(
                    {"run_id": run_id, "elapsed_ms": 0},
                    ensure_ascii=False,
                ),
            )
            await rt.diagnosis_repository.start_run(
                session_id,
                run_id,
                payload.ticket_id,
                "pending",
            )
            async for mode, chunk in rt.graph.astream(
                graph_input(payload, run_id, session_id),
                graph_config(session_id),
                stream_mode=["updates", "custom"],
            ):
                if await request.is_disconnected():
                    break
                if mode == "custom":
                    event = chunk.get("event", "progress")
                    data = {
                        "run_id": run_id,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "data": chunk.get("data"),
                    }
                    yield ServerSentEvent(
                        event=event,
                        data=json.dumps(data, ensure_ascii=False, default=str),
                    )
                elif "__interrupt__" in chunk:
                    yield ServerSentEvent(
                        event="approval_required",
                        data=json.dumps(chunk["__interrupt__"], ensure_ascii=False, default=str),
                    )
        except Exception as exc:  # noqa: BLE001
            await rt.diagnosis_repository.fail_run(run_id, str(exc))
            yield ServerSentEvent(
                event="error",
                data=json.dumps({"error": str(exc)}, ensure_ascii=False),
            )
        finally:
            SSE_CONNECTIONS.dec()

    return EventSourceResponse(events())


@router.post("/diagnoses/{session_id}/resume")
async def resume_diagnosis(
    session_id: str,
    payload: ResumeRequest,
    request: Request,
) -> dict[str, Any]:
    """使用人工决定恢复被中断的 LangGraph 任务。"""

    rt = runtime(request)
    decision = {
        "decision": payload.decision.value,
        "note": payload.note,
        "edited_payload": payload.edited_payload,
    }
    result = await rt.graph.ainvoke(Command(resume=decision), graph_config(session_id))
    return {"data": result}


@router.post("/policies/index")
async def index_policy(payload: PolicyIndexRequest, request: Request) -> dict[str, Any]:
    """创建政策版本并把解析和索引任务提交给 Celery。"""

    rt = runtime(request)
    version_id, job_id = await rt.knowledge_repository.create_version(
        title=payload.title,
        source_uri="api:text",
        version=payload.version,
        scene=payload.scene,
        content=payload.content,
    )
    task = index_policy_version.delay(version_id, job_id)
    return {"data": {"version_id": version_id, "job_id": job_id, "task_id": task.id}}


@router.post("/policies/search/debug")
async def search_debug(payload: SearchDebugRequest, request: Request) -> dict[str, Any]:
    """返回混合检索的排名和证据内容，便于调参。"""

    hits = await runtime(request).searcher.search(payload.query, payload.scene)
    return {"data": [hit.model_dump(mode="json") for hit in hits]}


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """返回工具 Manifest，不暴露处理函数。"""

    manifests = runtime(request).registry.manifests()
    return {"data": [manifest.model_dump(mode="json") for manifest in manifests]}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """返回 Prometheus 文本指标。"""

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
