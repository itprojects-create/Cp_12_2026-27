"""Shared stats helpers for the evaluation-expansion layer (§§11-22).

All functions are pure, deterministic, and tested on synthetics — never tuned
on the burned 2021-2026 window. Weak samples are flagged, not hidden.
"""
from __future__ import annotations

import math


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sharpe(daily: list[float], periods: int = 252) -> float:
    sd = stdev(daily)
    if sd <= 1e-12:
        return 0.0
    return mean(daily) / sd * math.sqrt(periods)


def sortino(daily: list[float], periods: int = 252) -> float:
    downside = [min(0.0, r) for r in daily]
    sd = math.sqrt(sum(x * x for x in downside) / len(downside)) if daily else 0.0
    if sd <= 1e-12:
        return 0.0
    return mean(daily) / sd * math.sqrt(periods)


def max_drawdown(equity: list[float]) -> tuple[float, int]:
    """(maxdd fraction, duration in bars). Equity must be cumulative wealth."""
    peak, mdd, dur, cur = equity[0], 0.0, 0, 0
    for v in equity:
        if v >= peak:
            peak, cur = v, 0
        else:
            cur += 1
            mdd = max(mdd, 1 - v / peak)
            dur = max(dur, cur)
    return mdd, dur


def cvar(daily: list[float], tail: float = 0.05) -> float:
    """Expected shortfall: mean of the worst `tail` fraction (negative = loss)."""
    if not daily:
        return 0.0
    k = max(1, int(math.ceil(len(daily) * tail)))
    return mean(sorted(daily)[:k])


def ols_alpha_beta(y: list[float], x: list[float]) -> dict:
    """R_candidate = alpha + beta * R_benchmark + eps (per-bar alpha).

    Returns alpha, beta, r_squared, n, and a low-confidence flag for n < 30 —
    regression alpha on weak samples must not be overstated (§11).
    """
    n = min(len(x), len(y))
    if n < 3:
        return {"alpha": 0.0, "beta": 0.0, "r_squared": 0.0, "n": n,
                "low_confidence": True}
    x, y = x[:n], y[:n]
    mx, my = mean(x), mean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sxx if sxx > 1e-18 else 0.0
    alpha = my - beta * mx
    syy = sum((yi - my) ** 2 for yi in y)
    r2 = (beta * beta * sxx / syy) if syy > 1e-18 else 0.0
    return {"alpha": alpha, "beta": beta, "r_squared": max(0.0, min(1.0, r2)),
            "n": n, "low_confidence": n < 30}


def ci95_mean(xs: list[float]) -> tuple[float, float]:
    """Normal-approx 95% CI for the mean (flagged small-n by callers)."""
    if len(xs) < 2:
        return (0.0, 0.0)
    m, se = mean(xs), stdev(xs) / math.sqrt(len(xs))
    return (m - 1.96 * se, m + 1.96 * se)
