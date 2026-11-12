"""Eval gate: a candidate retriever is adopted only if it beats the baseline on the golden set.

Rule (documented in docs/adr/0002): candidate must improve recall@k or MRR by at least `margin`
and must not lose more than `tolerance` on the other metric.
"""

Metrics = dict  # type: ignore[type-arg]


def verdict(
    baseline: Metrics, candidate: Metrics, margin: float = 0.05, tolerance: float = 0.02
) -> Metrics:
    d_recall = candidate["recall_at_k"] - baseline["recall_at_k"]
    d_mrr = candidate["mrr"] - baseline["mrr"]
    better = (d_recall >= margin and d_mrr >= -tolerance) or (
        d_mrr >= margin and d_recall >= -tolerance
    )
    return {
        "adopt": better,
        "delta_recall": round(d_recall, 4),
        "delta_mrr": round(d_mrr, 4),
        "rule": f"improve one metric by >= {margin} and lose at most {tolerance} on the other",
    }
