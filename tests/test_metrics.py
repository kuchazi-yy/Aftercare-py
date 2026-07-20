"""验证离线评测指标计算。"""

from ac_py.evaluation.metrics import ndcg_at_k, percentile, recall_at_k, reciprocal_rank


def test_retrieval_metrics() -> None:
    """相关文档位于第二名时指标应符合预期。"""

    predicted = ["a", "b", "c"]
    relevant = {"b"}
    assert recall_at_k(predicted, relevant, 3) == 1
    assert reciprocal_rank(predicted, relevant) == 0.5
    assert 0 < ndcg_at_k(predicted, relevant, 3) < 1


def test_percentile_interpolation() -> None:
    """百分位计算应对有序和无序输入保持一致。"""

    assert percentile([40, 10, 30, 20], 0.5) == 25
