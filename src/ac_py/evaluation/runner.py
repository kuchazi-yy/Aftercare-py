"""运行场景路由、工具筛选和 Elasticsearch 检索实验并汇总指标。"""

import json
import time
from dataclasses import dataclass
from statistics import mean

from ac_py.agent.prompt import count_tokens
from ac_py.agent.routing import classify_scenes
from ac_py.domain.schemas import SearchHit
from ac_py.evaluation.dataset import EvalCase
from ac_py.evaluation.metrics import ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from ac_py.rag.search import PolicySearcher
from ac_py.tools.registry import ToolRegistry


@dataclass(slots=True)
class EvaluationSummary:
    """保存一组实验的聚合结果。"""

    total: int
    scene_accuracy: float
    average_visible_tools: float
    recall_at_3: float | None = None
    mrr: float | None = None
    ndcg_at_3: float | None = None
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    all_tool_tokens: float | None = None
    scene_tool_tokens: float | None = None
    tool_token_reduction: float | None = None


def tool_schema_tokens(registry: ToolRegistry, names: set[str] | None = None) -> int:
    """估算指定工具完整 Schema 写入 Prompt 后占用的 Token。"""

    specs = []
    for name in registry.names:
        registered = registry.get(name)
        if registered is None:
            raise RuntimeError(f"工具注册表缺少已列出的工具: {name}")
        if names is None or name in names:
            specs.append(registered.spec)
    payload = [spec.model_dump(mode="json") for spec in specs]
    return count_tokens(json.dumps(payload, ensure_ascii=False))


def evaluate_routing(cases: list[EvalCase], registry: ToolRegistry) -> EvaluationSummary:
    """评估规则场景分类和场景工具过滤效果。"""

    correct = 0
    visible_counts: list[int] = []
    visible_tokens: list[int] = []
    all_tokens = tool_schema_tokens(registry)
    for case in cases:
        scenes, _ = classify_scenes(case.query, case.context)
        correct += int(case.scene in scenes)
        visible = registry.specs_for_scenes(set(scenes))
        visible_counts.append(len(visible))
        visible_tokens.append(tool_schema_tokens(registry, {spec.name for spec in visible}))
    total = len(cases)
    average_visible_tokens = mean(visible_tokens) if visible_tokens else 0
    return EvaluationSummary(
        total=total,
        scene_accuracy=correct / total if total else 0,
        average_visible_tools=mean(visible_counts) if visible_counts else 0,
        all_tool_tokens=float(all_tokens),
        scene_tool_tokens=average_visible_tokens,
        tool_token_reduction=(
            1 - average_visible_tokens / all_tokens if all_tokens and visible_tokens else 0
        ),
    )


async def evaluate_retrieval(
    cases: list[EvalCase],
    searcher: PolicySearcher,
) -> EvaluationSummary:
    """对带相关政策标题标注的样例运行真实检索并统计指标。"""

    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    for case in cases:
        if not case.relevant_titles:
            continue
        started = time.perf_counter()
        hits: list[SearchHit] = await searcher.search(case.query, case.scene)
        latencies.append((time.perf_counter() - started) * 1000)
        predicted = [hit.chunk.title for hit in hits]
        recalls.append(recall_at_k(predicted, case.relevant_titles, 3))
        reciprocal_ranks.append(reciprocal_rank(predicted, case.relevant_titles))
        ndcgs.append(ndcg_at_k(predicted, case.relevant_titles, 3))
    return EvaluationSummary(
        total=len(recalls),
        scene_accuracy=0,
        average_visible_tools=0,
        recall_at_3=mean(recalls) if recalls else 0,
        mrr=mean(reciprocal_ranks) if reciprocal_ranks else 0,
        ndcg_at_3=mean(ndcgs) if ndcgs else 0,
        latency_p50_ms=percentile(latencies, 0.5),
        latency_p95_ms=percentile(latencies, 0.95),
    )
