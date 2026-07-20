"""实现 Recall、MRR、nDCG 和百分位延迟等确定性评测指标。"""

import math


def recall_at_k(predicted: list[str], relevant: set[str], k: int) -> float:
    """计算前 K 个结果覆盖相关文档的比例。"""

    if not relevant:
        return 1.0
    return len(set(predicted[:k]) & relevant) / len(relevant)


def reciprocal_rank(predicted: list[str], relevant: set[str]) -> float:
    """计算首个相关结果的倒数排名。"""

    for rank, item in enumerate(predicted, start=1):
        if item in relevant:
            return 1 / rank
    return 0.0


def ndcg_at_k(predicted: list[str], relevant: set[str], k: int) -> float:
    """按二值相关性计算前 K 个结果的归一化折损累计增益。"""

    gains = [1.0 if item in relevant else 0.0 for item in predicted[:k]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 1.0


def percentile(values: list[float], ratio: float) -> float:
    """使用线性插值计算百分位数。"""

    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
