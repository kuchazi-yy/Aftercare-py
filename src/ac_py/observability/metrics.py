"""定义 HTTP、诊断阶段、检索、工具和模型延迟的 Prometheus 指标。"""

import time

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

HTTP_REQUESTS = Counter(
    "ac_http_requests_total",
    "HTTP 请求数量",
    ["method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "ac_http_request_duration_seconds",
    "HTTP 请求耗时",
    ["method", "path"],
)
STAGE_DURATION = Histogram(
    "ac_diagnosis_stage_duration_seconds",
    "诊断节点耗时",
    ["stage"],
)
TOOL_CALLS = Counter(
    "ac_tool_calls_total",
    "工具调用数量",
    ["tool", "status", "cached"],
)
RETRIEVAL_CANDIDATES = Histogram(
    "ac_retrieval_candidates",
    "进入精排的候选数量",
)
SSE_CONNECTIONS = Gauge("ac_sse_connections", "当前 SSE 连接数量")


class PrometheusMiddleware(BaseHTTPMiddleware):
    """统计所有 HTTP 请求的数量和耗时。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """执行下游请求并记录状态码与延迟。"""

        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_DURATION.labels(request.method, path).observe(time.perf_counter() - started)
        return response
