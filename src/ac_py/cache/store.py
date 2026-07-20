"""定义短期缓存、会话消息、幂等和锁所需的统一存储接口。"""

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from redis.asyncio import Redis

from ac_py.domain.schemas import ConversationTurn


class StateStore(Protocol):
    """描述 Agent 可依赖的短期状态存储能力。"""

    async def get_json(self, key: str) -> Any | None:
        """读取 JSON 值。"""

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        """写入带过期时间的 JSON 值。"""

    async def delete(self, *keys: str) -> None:
        """删除指定键。"""

    async def add_turn(self, session_id: str, turn: ConversationTurn, ttl_seconds: int) -> None:
        """向会话追加一轮消息。"""

    async def recent_turns(self, session_id: str, limit: int) -> list[ConversationTurn]:
        """读取会话最近若干轮消息。"""

    def lock(self, name: str, timeout_seconds: int) -> AbstractAsyncContextManager[bool]:
        """尝试持有短期分布式锁。"""

        ...


class RedisStateStore:
    """使用 Redis 保存可重建的短期状态，不承担永久事实存储。"""

    def __init__(self, url: str, prefix: str = "ac") -> None:
        """创建 Redis 客户端并设置统一键前缀。"""

        self._redis = Redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    def _key(self, key: str) -> str:
        """为业务键增加应用前缀，避免不同用途发生冲突。"""

        return f"{self._prefix}:{key}"

    async def get_json(self, key: str) -> Any | None:
        """读取并反序列化 JSON，键不存在时返回空值。"""

        value = await self._redis.get(self._key(key))
        return json.loads(value) if value is not None else None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        """序列化 JSON 并写入 Redis。"""

        await self._redis.set(self._key(key), json.dumps(value, ensure_ascii=False), ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        """删除一个或多个业务键。"""

        if keys:
            await self._redis.delete(*(self._key(key) for key in keys))

    async def add_turn(self, session_id: str, turn: ConversationTurn, ttl_seconds: int) -> None:
        """把会话消息写入列表并续期。"""

        key = self._key(f"session:{session_id}:turns")
        await self._redis.rpush(key, turn.model_dump_json())
        await self._redis.ltrim(key, -40, -1)
        await self._redis.expire(key, ttl_seconds)

    async def recent_turns(self, session_id: str, limit: int) -> list[ConversationTurn]:
        """读取最近消息并转换为领域对象。"""

        if limit <= 0:
            return []
        values = await self._redis.lrange(self._key(f"session:{session_id}:turns"), -limit, -1)
        return [ConversationTurn.model_validate_json(value) for value in values]

    @asynccontextmanager
    async def lock(self, name: str, timeout_seconds: int) -> AsyncIterator[bool]:
        """获取 Redis 锁，并在离开上下文时释放。"""

        lock = self._redis.lock(self._key(f"lock:{name}"), timeout=timeout_seconds)
        acquired = await lock.acquire(blocking=False)
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await lock.release()

    async def ping(self) -> bool:
        """检查 Redis 是否可用。"""

        return bool(await self._redis.ping())

    async def close(self) -> None:
        """关闭 Redis 连接池。"""

        await self._redis.aclose()
