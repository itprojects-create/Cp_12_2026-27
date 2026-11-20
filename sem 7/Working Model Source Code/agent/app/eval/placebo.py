"""Randomization / placebo tests: beat chance, not just the benchmark (§20).

Seeded shuffles + empirical p-values. The candidate must outperform reasonable
random alternatives; p-values are reported with the null size, never alone.
"""
from __future__ import annotations

import random


def permutation_pvalue(true_metric: float, null_metrics: list[float]) -> dict:
    """Empirical one-sided p-value with the +1 smoothing ((b+1)/(m+1))."""
    if not null_metrics:
        return {"p_value": 1.0, "n_null": 0, "beats_null": 0.0}
    beats = sum(1 for m in null_metrics if true_metric > m)
    return {"p_value": round((len(null_metrics) - beats + 1) / (len(null_metrics) + 1), 4),
            "n_null": len(null_metrics), "beats_null": round(beats / len(null_metrics), 4)}


def shuffled_labels(values: list[float], seed: int, n: int = 200) -> list[list[float]]:
    """n seeded shuffles of a label/return sequence (placebo timing)."""
    out = []
    for k in range(n):
        rng = random.Random(f"{seed}-{k}")
        seq = list(values)
        rng.shuffle(seq)
        out.append(seq)
    return out


def random_ranking_metric(true_metric: float, n_items: int, trials: int,
                          metric_fn, seed: int = 7) -> dict:
    """Null distribution from random rankings: metric_fn(random_order)."""
    rng = random.Random(seed)
    nulls = []
    for _ in range(trials):
        order = list(range(n_items))
        rng.shuffle(order)
        nulls.append(metric_fn(order))
    return {"null": nulls, **permutation_pvalue(true_metric, nulls)}
