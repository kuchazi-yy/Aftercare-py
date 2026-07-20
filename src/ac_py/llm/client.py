"""通过 OpenAI Compatible HTTP 接口调用向量、精排和聊天模型。"""

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx


class ModelClient(Protocol):
    """定义检索与 Agent 依赖的最小模型能力。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量。"""

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        """返回文档索引与精排分数。"""

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """流式生成回复 Token。"""
        yield ""


class OpenAICompatibleClient:
    """实现 SiliconFlow 等 OpenAI Compatible 服务的统一客户端。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        chat_model: str,
        embedding_model: str,
        rerank_model: str,
        timeout_seconds: float = 90,
    ) -> None:
        """创建复用连接池的异步 HTTP 客户端。"""

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.rerank_model = rerank_model
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 Embedding 接口并按输入顺序返回向量。"""

        self._require_key()
        response = await self.http.post(
            f"{self.base_url}/embeddings",
            json={"model": self.embedding_model, "input": texts},
        )
        response.raise_for_status()
        data = sorted(response.json().get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in data]

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        """调用 Cross-Encoder 精排接口并返回候选位置与相关分数。"""

        if not documents:
            return []
        self._require_key()
        response = await self.http.post(
            f"{self.base_url}/rerank",
            json={
                "model": self.rerank_model,
                "query": query,
                "documents": documents,
                "top_n": min(top_k, len(documents)),
                "return_documents": False,
            },
        )
        response.raise_for_status()
        return [
            (int(item["index"]), float(item["relevance_score"]))
            for item in response.json().get("results", [])
        ]

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """调用聊天接口并解析 SSE 数据块。"""

        self._require_key()
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": True,
            "enable_thinking": False,
        }
        async with self.http.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                token = self._parse_stream_line(line)
                if token:
                    yield token

    async def close(self) -> None:
        """关闭模型 HTTP 连接池。"""

        await self.http.aclose()

    def _require_key(self) -> None:
        """在发起远程请求前检查 API Key 与模型名称。"""

        if not self.api_key:
            raise RuntimeError("LLM_API_KEY 未配置")

    @staticmethod
    def _parse_stream_line(line: str) -> str:
        """从 OpenAI SSE 行中提取文本增量。"""

        if not line.startswith("data:"):
            return ""
        value = line.removeprefix("data:").strip()
        if not value or value == "[DONE]":
            return ""
        try:
            data: dict[str, Any] = json.loads(value)
        except json.JSONDecodeError:
            return ""
        choices = data.get("choices", [])
        if not choices:
            return ""
        content = choices[0].get("delta", {}).get("content")
        return content if isinstance(content, str) else ""
