"""提供测试专用的状态存储、模型、检索器和业务仓储替身。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from ac_py.domain.enums import Scene
from ac_py.domain.schemas import ConversationTurn, PolicyChunk, SearchHit


class FakeStateStore:
    """模拟测试所需的短期状态存储。"""

    def __init__(self) -> None:
        """初始化 JSON 与会话消息容器。"""

        self.values: dict[str, Any] = {}
        self.messages: dict[str, list[ConversationTurn]] = {}

    async def get_json(self, key: str) -> Any | None:
        """读取测试 JSON 值。"""

        return self.values.get(key)

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        """保存测试 JSON 值。"""

        self.values[key] = value

    async def delete(self, *keys: str) -> None:
        """删除测试 JSON 键。"""

        for key in keys:
            self.values.pop(key, None)

    async def add_turn(self, session_id: str, turn: ConversationTurn, ttl_seconds: int) -> None:
        """向测试会话追加消息。"""

        self.messages.setdefault(session_id, []).append(turn)

    async def recent_turns(self, session_id: str, limit: int) -> list[ConversationTurn]:
        """返回测试会话最近消息。"""

        return self.messages.get(session_id, [])[-limit:]

    @asynccontextmanager
    async def lock(self, name: str, timeout_seconds: int) -> AsyncIterator[bool]:
        """模拟始终可获得的测试锁。"""

        yield True


class FakeModel:
    """模拟向量、精排和流式回复。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """为每段文本返回固定测试向量。"""

        return [[1.0, 0.0] for _ in texts]

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        """按原顺序返回前若干候选。"""

        return [(index, 1 - index / 10) for index in range(min(top_k, len(documents)))]

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """流式返回固定中文回复。"""

        for token in "请依据退款政策处理。":
            yield token


class FakeSearcher:
    """返回一条确定政策证据。"""

    async def search(
        self,
        query: str,
        scene: Scene,
        at_time: Any = None,
    ) -> list[SearchHit]:
        """根据场景创建测试命中。"""

        chunk = PolicyChunk(
            chunk_id="refund-1",
            document_id="refund",
            version="v1",
            title="退款到账时效",
            level="child",
            scene=scene,
            content="审核通过后按原支付渠道退回。",
        )
        return [SearchHit(chunk=chunk, rerank_score=0.95)]


class FakeBusinessRepository:
    """提供 14 个工具所需的固定业务事实。"""

    def __init__(self) -> None:
        """初始化测试写入记录。"""

        self.records: list[dict[str, Any]] = []

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        """返回测试工单。"""

        return {"id": ticket_id, "status": "open"}

    async def get_order_for_ticket(self, ticket_id: int) -> dict[str, Any]:
        """返回测试订单。"""

        return {"id": 1, "status": "paid"}

    async def get_history(self, ticket_id: int) -> list[dict[str, Any]]:
        """返回测试处理历史。"""

        return []

    async def get_refund(self, ticket_id: int) -> dict[str, Any]:
        """返回测试退款记录。"""

        return {"status": "approved", "timeline": []}

    async def get_return_request(self, ticket_id: int) -> dict[str, Any]:
        """返回测试退货记录。"""

        return {}

    async def get_logistics(self, ticket_id: int) -> dict[str, Any]:
        """返回测试物流记录。"""

        return {"status": "shipping"}

    async def get_product(self, ticket_id: int) -> dict[str, Any]:
        """返回测试商品。"""

        return {"name": "水杯"}

    async def create_ticket_record(
        self,
        ticket_id: int,
        operator: str,
        action: str,
        content: str,
    ) -> dict[str, Any]:
        """返回模拟写入记录。"""

        record = {"ticket_id": ticket_id, "action": action, "content": content}
        self.records.append(record)
        return record
