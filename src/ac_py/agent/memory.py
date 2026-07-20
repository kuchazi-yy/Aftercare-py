"""组装会话短期记忆，并在 Token 超预算时生成可追溯摘要。"""

from ac_py.cache.store import StateStore
from ac_py.domain.schemas import ConversationTurn


class MemoryManager:
    """管理最近对话、已有摘要与异步压缩输入。"""

    def __init__(self, store: StateStore, recent_turns: int, session_ttl_seconds: int) -> None:
        """保存状态存储和会话窗口配置。"""

        self.store = store
        self.recent_turn_limit = recent_turns * 2
        self.session_ttl_seconds = session_ttl_seconds

    async def load(self, session_id: str) -> tuple[str, list[ConversationTurn]]:
        """读取会话摘要和最近四轮原始消息。"""

        summary = await self.store.get_json(f"session:{session_id}:summary") or ""
        turns = await self.store.recent_turns(session_id, self.recent_turn_limit)
        return str(summary), turns

    async def append(self, session_id: str, role: str, content: str) -> None:
        """向短期会话追加消息。"""

        await self.store.add_turn(
            session_id,
            ConversationTurn(role=role, content=content),
            self.session_ttl_seconds,
        )

    async def compact(self, session_id: str, token_threshold: int = 2400) -> str | None:
        """对超出 Token 阈值的旧消息做确定性压缩，避免阻塞在线回复。"""

        turns = await self.store.recent_turns(session_id, 40)
        approximate_tokens = sum(max(1, len(turn.content) // 2) for turn in turns)
        if approximate_tokens <= token_threshold or len(turns) <= self.recent_turn_limit:
            return None
        old_turns = turns[: -self.recent_turn_limit]
        summary = "；".join(f"{turn.role}:{turn.content[:160]}" for turn in old_turns)
        await self.store.set_json(
            f"session:{session_id}:summary",
            summary,
            self.session_ttl_seconds,
        )
        return summary
