"""创建版本化 Elasticsearch 索引，批量向量化政策并通过 Alias 发布。"""

from datetime import UTC, datetime
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError, helpers

from ac_py.config import Settings
from ac_py.domain.schemas import PolicyChunk
from ac_py.llm.client import ModelClient


class PolicyIndexer:
    """负责政策索引的构建、验证和原子发布。"""

    def __init__(
        self,
        client: AsyncElasticsearch,
        model: ModelClient,
        settings: Settings,
    ) -> None:
        """保存 Elasticsearch、模型和索引配置。"""

        self.client = client
        self.model = model
        self.settings = settings

    async def build(self, chunks: list[PolicyChunk], batch_size: int = 32) -> str:
        """批量生成向量、写入新索引并返回索引名称。"""

        index_name = f"aftercare-policies-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        await self.client.indices.create(index=index_name, mappings=self._mappings())
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = await self.model.embed([f"{item.title}\n{item.content}" for item in batch])
            actions = []
            for chunk, vector in zip(batch, vectors, strict=True):
                source = chunk.model_copy(update={"embedding": vector}).model_dump(mode="json")
                actions.append({"_index": index_name, "_id": chunk.chunk_id, "_source": source})
            await helpers.async_bulk(self.client, actions)
        await self.client.indices.refresh(index=index_name)
        return index_name

    async def publish(self, index_name: str) -> None:
        """验证目标索引存在后原子切换线上 Alias。"""

        if not await self.client.indices.exists(index=index_name):
            raise ValueError(f"索引不存在: {index_name}")
        try:
            response = await self.client.indices.get_alias(
                index="*",
                name=self.settings.elasticsearch_alias,
            )
            current: dict[str, Any] = response.body
        except NotFoundError:
            current = {}
        actions = [
            {"remove": {"index": name, "alias": self.settings.elasticsearch_alias}}
            for name in current
        ]
        actions.append({"add": {"index": index_name, "alias": self.settings.elasticsearch_alias}})
        await self.client.indices.update_aliases(actions=actions)

    def _mappings(self) -> dict[str, object]:
        """返回政策父子块使用的 Elasticsearch 映射。"""

        return {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "version": {"type": "keyword"},
                "title": {"type": "text"},
                "parent_id": {"type": "keyword"},
                "level": {"type": "keyword"},
                "scene": {"type": "keyword"},
                "content": {"type": "text"},
                "effective_from": {"type": "date"},
                "effective_to": {"type": "date"},
                "active": {"type": "boolean"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": self.settings.embedding_dimensions,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        }
