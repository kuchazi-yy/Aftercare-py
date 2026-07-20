"""在应用启动时装配数据库、Redis、Elasticsearch、模型和 LangGraph。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from ac_py.agent.memory import MemoryManager
from ac_py.agent.workflow import AgentServices, create_workflow
from ac_py.cache.store import RedisStateStore
from ac_py.config import Settings, get_settings
from ac_py.db.base import Database
from ac_py.db.repositories import BusinessRepository, DiagnosisRepository, KnowledgeRepository
from ac_py.llm.client import OpenAICompatibleClient
from ac_py.rag.search import ElasticsearchPolicySearcher
from ac_py.tools.builtin import create_business_registry
from ac_py.tools.executor import ToolExecutor
from ac_py.tools.registry import ToolRegistry


@dataclass(slots=True)
class Runtime:
    """保存 FastAPI 请求处理所需的共享运行时对象。"""

    settings: Settings
    database: Database
    state_store: RedisStateStore
    elasticsearch: AsyncElasticsearch
    model: OpenAICompatibleClient
    business_repository: BusinessRepository
    diagnosis_repository: DiagnosisRepository
    knowledge_repository: KnowledgeRepository
    searcher: ElasticsearchPolicySearcher
    registry: ToolRegistry
    graph: Any


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """初始化外部依赖与 LangGraph，并在关闭时释放连接。"""

    settings = get_settings()
    database = Database(settings)
    await database.create_schema()
    state_store = RedisStateStore(settings.redis_url)
    elasticsearch = AsyncElasticsearch(settings.elasticsearch_url)
    model = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.embedding_model,
        settings.rerank_model,
    )
    business_repository = BusinessRepository(database.session_factory)
    diagnosis_repository = DiagnosisRepository(database.session_factory)
    knowledge_repository = KnowledgeRepository(database.session_factory)
    registry = create_business_registry(business_repository)
    executor = ToolExecutor(
        registry,
        state_store,
        diagnosis_repository,
        settings.cache_business_seconds,
    )
    memory = MemoryManager(state_store, settings.recent_turns, settings.checkpoint_ttl_seconds)
    searcher = ElasticsearchPolicySearcher(elasticsearch, model, state_store, settings)
    ttl_minutes = max(1, settings.checkpoint_ttl_seconds // 60)

    async with AsyncRedisSaver.from_conn_string(
        settings.redis_url,
        ttl={"default_ttl": ttl_minutes, "refresh_on_read": True},
        checkpoint_prefix="ac_checkpoint",
        checkpoint_write_prefix="ac_checkpoint_write",
    ) as checkpointer:
        await checkpointer.asetup()
        graph = create_workflow(
            AgentServices(
                settings=settings,
                model=model,
                searcher=searcher,
                registry=registry,
                executor=executor,
                memory=memory,
                diagnosis_repository=diagnosis_repository,
            ),
            checkpointer,
        )
        app.state.runtime = Runtime(
            settings=settings,
            database=database,
            state_store=state_store,
            elasticsearch=elasticsearch,
            model=model,
            business_repository=business_repository,
            diagnosis_repository=diagnosis_repository,
            knowledge_repository=knowledge_repository,
            searcher=searcher,
            registry=registry,
            graph=graph,
        )
        yield

    await model.close()
    await elasticsearch.close()
    await state_store.close()
    await database.close()


def get_runtime(app: FastAPI) -> Runtime:
    """从 FastAPI 应用状态读取已初始化运行时。"""

    return cast(Runtime, app.state.runtime)
