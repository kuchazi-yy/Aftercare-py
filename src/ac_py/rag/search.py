"""使用 Elasticsearch 完成 BM25、dense kNN、RRF 融合、精排与父块补全。"""

import asyncio
import hashlib
from datetime import datetime
from typing import Any, Protocol

from elasticsearch import AsyncElasticsearch

from ac_py.cache.store import StateStore
from ac_py.config import Settings
from ac_py.domain.enums import Scene
from ac_py.domain.schemas import PolicyChunk, SearchHit
from ac_py.llm.client import ModelClient


class PolicySearcher(Protocol):
    """定义诊断工作流所需的政策检索能力。"""

    async def search(
        self,
        query: str,
        scene: Scene,
        at_time: datetime | None = None,
    ) -> list[SearchHit]:
        """返回最终政策证据。"""


class ElasticsearchPolicySearcher:
    """实现 Elasticsearch 单引擎混合检索与渐进式父块补全。"""

    def __init__(
        self,
        client: AsyncElasticsearch,
        model: ModelClient,
        state_store: StateStore,
        settings: Settings,
    ) -> None:
        """保存检索依赖与候选规模配置。"""

        self.client = client
        self.model = model
        self.state_store = state_store
        self.settings = settings

    async def search(
        self,
        query: str,
        scene: Scene,
        at_time: datetime | None = None,
    ) -> list[SearchHit]:
        """并发执行 BM25 与向量召回，融合、精排并补充父章节。"""

        cache_key = await self._cache_key(query, scene, at_time)
        cached = await self.state_store.get_json(cache_key)
        if cached is not None:
            return [SearchHit.model_validate(item) for item in cached]

        vector = await self._embedding(query)
        filters = self._filters(scene, at_time)
        bm25_hits, dense_hits = await asyncio.gather(
            self._bm25(query, filters, self.settings.bm25_top_k),
            self._dense(vector, filters, self.settings.dense_top_k),
        )
        fused = self._rrf(bm25_hits, dense_hits)
        ranked = await self._rerank(query, fused, self.settings.rerank_top_k)
        expanded = await self._expand_parents(ranked)
        await self.state_store.set_json(
            cache_key,
            [hit.model_dump(mode="json") for hit in expanded],
            self.settings.cache_policy_seconds,
        )
        return expanded

    async def _bm25(
        self,
        query: str,
        filters: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """执行字段加权的 BM25 召回。"""

        response = await self.client.search(
            index=self.settings.elasticsearch_alias,
            size=top_k,
            query={
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "content", "scene^2"],
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            source_excludes=["embedding"],
        )
        return list(response["hits"]["hits"])

    async def _dense(
        self,
        vector: list[float],
        filters: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """执行带业务过滤的 dense kNN 召回。"""

        response = await self.client.search(
            index=self.settings.elasticsearch_alias,
            size=top_k,
            knn={
                "field": "embedding",
                "query_vector": vector,
                "k": top_k,
                "num_candidates": max(50, top_k * 5),
                "filter": filters,
            },
            source_excludes=["embedding"],
        )
        return list(response["hits"]["hits"])

    async def _rerank(
        self,
        query: str,
        hits: list[SearchHit],
        top_k: int,
    ) -> list[SearchHit]:
        """使用 BGE Cross-Encoder 精排融合候选并保留 TopK。"""

        if not hits:
            return []
        documents = [f"{hit.chunk.title}\n{hit.chunk.content}" for hit in hits]
        ranking = await self.model.rerank(query, documents, min(top_k, len(hits)))
        output: list[SearchHit] = []
        for index, score in ranking:
            hit = hits[index].model_copy(deep=True)
            hit.rerank_score = score
            output.append(hit)
        return output

    async def _expand_parents(self, hits: list[SearchHit]) -> list[SearchHit]:
        """只为最终 Top3 子块读取父章节，控制进入 Prompt 的上下文规模。"""

        parent_ids = {hit.chunk.parent_id for hit in hits if hit.chunk.parent_id}
        if not parent_ids:
            return hits
        response = await self.client.mget(
            index=self.settings.elasticsearch_alias,
            ids=sorted(parent_ids),
            source_excludes=["embedding"],
        )
        parents = {
            document["_id"]: document.get("_source", {})
            for document in response.get("docs", [])
            if document.get("found")
        }
        output: list[SearchHit] = []
        for hit in hits:
            source = parents.get(hit.chunk.parent_id or "")
            if source:
                child_content = hit.chunk.content
                parent_content = str(source.get("content", ""))
                hit.chunk.content = f"命中条款：{child_content}\n所属章节：{parent_content}"
            output.append(hit)
        return output

    @staticmethod
    def _rrf(
        bm25_hits: list[dict[str, Any]],
        dense_hits: list[dict[str, Any]],
        k: int = 60,
    ) -> list[SearchHit]:
        """使用排名而非原始分数融合两路不同量纲的召回结果。"""

        merged: dict[str, SearchHit] = {}
        for source_name, items in (("bm25", bm25_hits), ("dense", dense_hits)):
            for rank, item in enumerate(items, start=1):
                chunk_id = str(item["_id"])
                hit = merged.get(chunk_id)
                if hit is None:
                    hit = SearchHit(chunk=PolicyChunk.model_validate(item["_source"]))
                    merged[chunk_id] = hit
                hit.rrf_score += 1 / (k + rank)
                if source_name == "bm25":
                    hit.bm25_rank = rank
                else:
                    hit.dense_rank = rank
        return sorted(merged.values(), key=lambda item: item.rrf_score, reverse=True)

    @staticmethod
    def _filters(scene: Scene, at_time: datetime | None) -> list[dict[str, Any]]:
        """构建场景、激活状态和政策生效时间过滤条件。"""

        filters: list[dict[str, Any]] = [
            {"term": {"active": True}},
            {"terms": {"scene": [scene.value, Scene.OTHER.value]}},
            {"terms": {"level": ["child", "atomic"]}},
        ]
        if at_time is not None:
            timestamp = at_time.isoformat()
            filters.extend(
                [
                    {
                        "bool": {
                            "should": [
                                {"range": {"effective_from": {"lte": timestamp}}},
                                {"bool": {"must_not": {"exists": {"field": "effective_from"}}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    {
                        "bool": {
                            "should": [
                                {"range": {"effective_to": {"gte": timestamp}}},
                                {"bool": {"must_not": {"exists": {"field": "effective_to"}}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                ]
            )
        return filters

    async def _embedding(self, query: str) -> list[float]:
        """复用相同 Query 的向量，减少候选规模实验和重复检索的远程调用。"""

        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        cache_key = f"embedding:{self.settings.embedding_model}:{digest}"
        cached = await self.state_store.get_json(cache_key)
        if cached is not None:
            return [float(value) for value in cached]
        vector = (await self.model.embed([query]))[0]
        await self.state_store.set_json(cache_key, vector, self.settings.cache_policy_seconds)
        return vector

    async def _cache_key(
        self,
        query: str,
        scene: Scene,
        at_time: datetime | None,
    ) -> str:
        """生成包含索引别名、场景和时间约束的检索缓存键。"""

        response = await self.client.indices.get_alias(name=self.settings.elasticsearch_alias)
        index_version = ",".join(sorted(response.body))
        raw = (
            f"{index_version}|{scene}|{at_time}|{query}|"
            f"{self.settings.bm25_top_k}|{self.settings.dense_top_k}|"
            f"{self.settings.rerank_top_k}"
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"rag:{digest}"
