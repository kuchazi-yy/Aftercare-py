"""提供命令行入口，执行 200 条数据的路由与工具可见性实验。"""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from elasticsearch import AsyncElasticsearch

from ac_py.cache.store import RedisStateStore
from ac_py.config import get_settings
from ac_py.db.base import Database
from ac_py.db.repositories import BusinessRepository
from ac_py.evaluation.dataset import load_cases
from ac_py.evaluation.runner import evaluate_retrieval, evaluate_routing
from ac_py.llm.client import OpenAICompatibleClient
from ac_py.rag.search import ElasticsearchPolicySearcher
from ac_py.tools.builtin import create_business_registry


def build_parser() -> argparse.ArgumentParser:
    """创建评测命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="运行 AC-py 离线评测")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--retrieval", action="store_true")
    return parser


async def run(dataset: Path, retrieval: bool) -> dict[str, object]:
    """执行路由实验，并按需连接 Elasticsearch 执行检索实验。"""

    settings = get_settings()
    cases = load_cases(dataset)
    database = Database(settings)
    registry = create_business_registry(BusinessRepository(database.session_factory))
    report: dict[str, object] = {"routing": asdict(evaluate_routing(cases, registry))}
    if retrieval:
        store = RedisStateStore(settings.redis_url)
        elasticsearch = AsyncElasticsearch(settings.elasticsearch_url)
        model = OpenAICompatibleClient(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            settings.embedding_model,
            settings.rerank_model,
        )
        try:
            searcher = ElasticsearchPolicySearcher(elasticsearch, model, store, settings)
            report["retrieval"] = asdict(await evaluate_retrieval(cases, searcher))
        finally:
            await model.close()
            await elasticsearch.close()
            await store.close()
    await database.close()
    return report


def main() -> None:
    """解析参数、运行评测并输出 JSON 报告。"""

    args = build_parser().parse_args()
    print(json.dumps(asyncio.run(run(args.dataset, args.retrieval)), ensure_ascii=False, indent=2))
