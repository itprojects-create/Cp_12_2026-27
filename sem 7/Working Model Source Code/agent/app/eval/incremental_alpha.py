"""Incremental-alpha evaluation: candidate vs champion/benchmark/controls (§11).

A candidate must not pass merely because raw return improved. Every report
carries beta-explained return, estimated alpha (with weak-sample flags),
incremental Sharpe/MaxDD/turnover/cost/CVaR, and CIs where feasible.
"""
from __future__ import annotations

from app.eval import stats as S


def evaluate(candidate_daily: list[float], champion_daily: list[float],
             benchmark_daily: list[float], candidate_turnover: float = 0.0,
             champion_turnover: float = 0.0, roundtrip_cost: float = 0.0021,
             beta_matched_daily: list[float] | None = None) -> dict:
    """Compare aligned daily net-return series. All lists same length (truncated
    to shortest). Cost terms are informational here — series are expected
    net-of-costs already; turnover/cost rows quantify the *difference*."""
    n = min(len(candidate_daily), len(champion_daily), len(benchmark_daily))
    if n < 2:
        return {"n": n, "insufficient_data": True}
    c, h, b = candidate_daily[:n], champion_daily[:n], benchmark_daily[:n]
    reg = S.ols_alpha_beta(c, b)
    raw_c, raw_b = sum(c), sum(b)
    beta_explained = reg["beta"] * raw_b
    eq_c = _equity(c)
    mdd_c, dur_c = S.max_drawdown(eq_c)
    eq_h = _equity(h)
    mdd_h, _ = S.max_drawdown(eq_h)
    incremental_cost = (candidate_turnover - champion_turnover) * roundtrip_cost
    out = {
        "n": n,
        "raw_return": round(raw_c, 6),
        "benchmark_return": round(raw_b, 6),
        "candidate_beta": round(reg["beta"], 4),
        "beta_explained_return": round(beta_explained, 6),
        "estimated_alpha": round(raw_c - beta_explained, 6),
        "alpha_low_confidence": reg["low_confidence"],
        "r_squared": round(reg["r_squared"], 4),
        "incremental_return_vs_champion": round(sum(c) - sum(h), 6),
        "incremental_sharpe": round(S.sharpe(c) - S.sharpe(h), 4),
        "incremental_maxdd": round(mdd_c - mdd_h, 4),
        "candidate_maxdd": round(mdd_c, 4),
        "drawdown_duration": dur_c,
        "incremental_turnover": round(candidate_turnover - champion_turnover, 4),
        "incremental_cost": round(incremental_cost, 6),
        "incremental_cvar": round(S.cvar(c) - S.cvar(h), 6),
        "alpha_ci95": [round(v, 6) for v in S.ci95_mean(
            [ci - reg["beta"] * bi for ci, bi in zip(c, b)])],
    }
    if beta_matched_daily:
        m = beta_matched_daily[:n]
        out["vs_beta_matched"] = round(sum(c) - sum(m), 6)
    return out


def _equity(daily: list[float]) -> list[float]:
    eq, v = [], 1.0
    for r in daily:
        v *= 1.0 + r
        eq.append(v)
    return eq
