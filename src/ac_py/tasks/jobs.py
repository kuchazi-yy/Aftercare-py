"""实现政策解析与 Elasticsearch 重建等可重试后台任务。"""

import asyncio

from elasticsearch import AsyncElasticsearch

from ac_py.config import get_settings
from ac_py.db.base import Database
from ac_py.db.repositories import KnowledgeRepository
from ac_py.domain.enums import Scene
from ac_py.llm.client import OpenAICompatibleClient
from ac_py.rag.chunking import split_policy
from ac_py.rag.indexer import PolicyIndexer
from ac_py.tasks.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def index_policy_version(self: object, version_id: int, job_id: int) -> dict[str, object]:
    """在 Celery Worker 中执行异步政策索引任务。"""

    return asyncio.run(_index_policy_version(version_id, job_id))


async def _index_policy_version(version_id: int, job_id: int) -> dict[str, object]:
    """读取政策版本、切分、向量化、发布索引并更新任务状态。"""

    settings = get_settings()
    database = Database(settings)
    elasticsearch = AsyncElasticsearch(settings.elasticsearch_url)
    model = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.embedding_model,
        settings.rerank_model,
    )
    repository = KnowledgeRepository(database.session_factory)
    try:
        row = await repository.get_version(version_id)
        if row is None:
            raise ValueError("政策版本不存在")
        version, document = row
        chunks = split_policy(
            document_id=str(document.id),
            version=version.version,
            title=document.title,
            text=version.content,
            scene=Scene(version.scene),
            effective_from=version.effective_from,
            effective_to=version.effective_to,
        )
        await repository.save_chunks(version_id, chunks)
        indexer = PolicyIndexer(elasticsearch, model, settings)
        index_name = await indexer.build(chunks)
        await indexer.publish(index_name)
        await repository.finish_index_job(version_id, job_id, index_name)
        return {"index_name": index_name, "chunks": len(chunks)}
    except Exception as exc:
        await repository.fail_index_job(job_id, str(exc))
        raise
    finally:
        await model.close()
        await elasticsearch.close()
        await database.close()
