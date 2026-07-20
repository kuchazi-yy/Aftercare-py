"""测量 SSE 端到端延迟及不同输入 Token 规模下的模型 TTFT。"""

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx

from ac_py.agent.prompt import count_tokens, trim_to_tokens
from ac_py.config import get_settings
from ac_py.evaluation.metrics import percentile
from ac_py.llm.client import OpenAICompatibleClient


def parse_args() -> argparse.Namespace:
    """解析基准模式、重复次数和输出路径。"""

    parser = argparse.ArgumentParser(description="运行 AC-py 延迟基准")
    parser.add_argument("mode", choices=("api", "model"))
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--api-url", default="http://127.0.0.1:8080")
    parser.add_argument("--ticket-id", type=int, default=1)
    parser.add_argument("--model-interval", type=float, default=2.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def summarize(values: list[float]) -> dict[str, float]:
    """汇总一组毫秒耗时的 P50 与 P95。"""

    return {
        "p50_ms": round(percentile(values, 0.5), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
    }


async def measure_api_once(client: httpx.AsyncClient, url: str, ticket_id: int) -> dict[str, float]:
    """消费一次 SSE 诊断并记录首事件、首正文和总耗时。"""

    started = time.perf_counter()
    first_event: float | None = None
    first_token: float | None = None
    event = ""
    payload = {
        "ticket_id": ticket_id,
        "session_id": f"benchmark-{uuid.uuid4().hex}",
        "message": "退款审核通过两天了，为什么还没到账？",
    }
    async with client.stream(
        "POST",
        f"{url.rstrip('/')}/api/v1/diagnoses/stream",
        json=payload,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            elapsed = (time.perf_counter() - started) * 1000
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                if first_event is None:
                    first_event = elapsed
                if event == "message" and first_token is None:
                    first_token = elapsed
            elif line.startswith("data:") and event == "error":
                raise RuntimeError(line.removeprefix("data:").strip())
    if first_event is None or first_token is None:
        raise RuntimeError("SSE 未返回首事件或模型正文")
    return {
        "first_event_ms": first_event,
        "first_token_ms": first_token,
        "total_ms": (time.perf_counter() - started) * 1000,
    }


async def benchmark_api(url: str, ticket_id: int, repeats: int) -> dict[str, object]:
    """顺序执行多次完整诊断，避免并发负载混入单请求延迟。"""

    rows: list[dict[str, float]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        for _ in range(repeats):
            rows.append(await measure_api_once(client, url, ticket_id))
    return {
        "repeats": repeats,
        "first_event": summarize([row["first_event_ms"] for row in rows]),
        "ttft": summarize([row["first_token_ms"] for row in rows]),
        "total": summarize([row["total_ms"] for row in rows]),
    }


def build_token_input(token_count: int) -> str:
    """构造并裁剪到目标通用 Token 数的中文政策文本。"""

    unit = "售后政策要求先核对订单、退款和物流状态，再依据有效条款答复。"
    text = unit
    while count_tokens(text) < token_count:
        text += unit
    return trim_to_tokens(text, token_count)


async def measure_model_once(
    model: OpenAICompatibleClient,
    content: str,
) -> dict[str, float]:
    """调用一次关闭思考模式的模型并记录首正文及总耗时。"""

    started = time.perf_counter()
    first_token: float | None = None
    output = []
    async for token in model.stream_chat(
        [
            {"role": "system", "content": "只回复收到。"},
            {"role": "user", "content": content},
        ],
        16,
    ):
        if first_token is None:
            first_token = (time.perf_counter() - started) * 1000
        output.append(token)
    if first_token is None or not output:
        raise RuntimeError("模型未返回正文")
    return {
        "first_token_ms": first_token,
        "total_ms": (time.perf_counter() - started) * 1000,
    }


async def benchmark_model(repeats: int, interval_seconds: float) -> dict[str, object]:
    """对五档输入 Token 规模分别执行重复模型延迟测试。"""

    settings = get_settings()
    model = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.embedding_model,
        settings.rerank_model,
    )
    report: dict[str, object] = {"repeats": repeats, "groups": {}}
    try:
        groups = report["groups"]
        assert isinstance(groups, dict)
        for token_count in (1000, 2000, 4000, 6000, 8000):
            content = build_token_input(token_count)
            rows = []
            for repeat_index in range(repeats):
                rows.append(await measure_model_once(model, content))
                if interval_seconds > 0 and repeat_index < repeats - 1:
                    await asyncio.sleep(interval_seconds)
            groups[str(token_count)] = {
                "estimated_input_tokens": count_tokens(content),
                "ttft": summarize([row["first_token_ms"] for row in rows]),
                "total": summarize([row["total_ms"] for row in rows]),
            }
        return report
    finally:
        await model.close()


async def run(args: argparse.Namespace) -> dict[str, object]:
    """根据命令行模式运行 API 或模型基准。"""

    if args.mode == "api":
        return await benchmark_api(args.api_url, args.ticket_id, args.repeats)
    return await benchmark_model(args.repeats, args.model_interval)


def main() -> None:
    """执行基准并将 JSON 写入终端及可选文件。"""

    args = parse_args()
    report = asyncio.run(run(args))
    content = json.dumps(report, ensure_ascii=False, indent=2)
    print(content)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
