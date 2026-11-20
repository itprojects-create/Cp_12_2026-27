"""Benchmark attribution: active return/risk, IR, betas, captures (§13).

Never compare a broad equity strategy only against cash: every report carries
benchmark-relative anatomy where a benchmark series is available.
"""
from __future__ import annotations

from app.eval import stats as S


def attribute(candidate_daily: list[float], benchmark_daily: list[float]) -> dict:
    n = min(len(candidate_daily), len(benchmark_daily))
    if n < 2:
        return {"n": n, "insufficient_data": True}
    c, b = candidate_daily[:n], benchmark_daily[:n]
    active = [ci - bi for ci, bi in zip(c, b)]
    reg = S.ols_alpha_beta(c, b)
    up = [(ci, bi) for ci, bi in zip(c, b) if bi > 0]
    down = [(ci, bi) for ci, bi in zip(c, b) if bi < 0]
    up_cap = (sum(ci for ci, _ in up) / sum(bi for _, bi in up)) if up else 0.0
    down_cap = (sum(ci for ci, _ in down) / sum(bi for _, bi in down)) if down else 0.0
    ar = S.stdev(active)
    return {"n": n,
            "active_return": round(sum(active), 6),
            "active_risk": round(ar * (252 ** 0.5), 6),
            "information_ratio": round((S.mean(active) / ar * (252 ** 0.5)) if ar > 1e-12 else 0.0, 4),
            "beta": round(reg["beta"], 4),
            "alpha": round(sum(c) - reg["beta"] * sum(b), 6),
            "alpha_low_confidence": reg["low_confidence"],
            "up_capture": round(up_cap, 4),
            "down_capture": round(down_cap, 4),
            "sharpe": round(S.sharpe(c), 4),
            "sortino": round(S.sortino(c), 4)}


def compare_many(candidate_daily: list[float],
                 benchmarks: dict[str, list[float]]) -> dict:
    """Attribute against several benchmarks (TRI, equal-weight, cash, champion)."""
    return {name: attribute(candidate_daily, series) for name, series in benchmarks.items()}
