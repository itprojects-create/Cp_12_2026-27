"""Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) + trial registry (Day-5 prereg §§1-2).

Haircuts the headline Sharpe for the number of configurations tried on the
same window. Pure python (erf-based Normal CDF), deterministic.
V estimated as sample variance across the K registered trial Sharpes
(documented approximation; preregistered choice, not tuned).
"""
from __future__ import annotations

import math

EULER_GAMMA = 0.5772156649

# Prereg §1: every return/Sharpe configuration ever measured on 2021-2026.
# Agent direction evals are a separate claim family (accuracy) — excluded here.
TRIALS: tuple[tuple[str, float, str], ...] = (
    ("v1-exposure-bug", 0.80, "prereg_core_v2_exposure.md"),
    ("v2", 0.698, "core_backtest_20261006.json"),
    ("v3-narrow", 0.705, "core_backtest_v3.json"),
    ("v3-broad", 0.853, "core_backtest_v3_broad.json"),
    ("v3+veto-overlay", 0.776, "overlay_vs_core_20261007.json"),
    ("v4-narrow", 0.687, "core_backtest_v4_nifty50.json"),
    ("v4-broad", 1.509, "core_backtest_v4_broad.json"),
    ("paper-narrow-flat", 0.69, "paper_10L_nifty50.json"),
    ("paper-broad-flat", 1.51, "paper_10L_broad.json"),
    ("paper-narrow-env", 0.69, "paper_10L_nifty50_env.json"),
    # Blind 2015-2020 trials (prereg_blind_2015_2020.md): rule never saw this
    # window during design. Added AFTER the one-shot runs completed.
    ("blind-narrow-2015-2020", 1.508, "core_backtest_v4_nifty50_2015-01-01_2020-12-31.json"),
    ("blind-broad-2015-2020", 1.508, "core_backtest_v4_broad_2015-01-01_2020-12-31.json"),
)
K = len(TRIALS)


def phi_inv(p: float) -> float:
    """Acklam-style inverse Normal CDF via erf inversion (bisection, deterministic)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0,1)")
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def Phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def expected_sr_null(sharpes: list[float]) -> float:
    """Expected max Sharpe under the null given K trials (V from sample variance)."""
    k = len(sharpes)
    if k < 2:
        return 0.0
    mu = sum(sharpes) / k
    var = sum((s - mu) ** 2 for s in sharpes) / (k - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var) * ((1 - EULER_GAMMA) * phi_inv(1 - 1 / k)
                             + EULER_GAMMA * phi_inv(1 - 1 / (k * math.e)))


def dsr(sr: float, t_obs: int, skew: float, kurtosis: float,
        sharpes: list[float] | None = None) -> dict:
    """Deflated Sharpe Ratio for observed SR with t_obs returns.
    kurtosis = Pearson (normal == 3). Returns {dsr, sr0_null, trials}."""
    trials = sharpes if sharpes is not None else [s for _, s, _ in TRIALS]
    sr0 = expected_sr_null(trials)
    denom = 1 - skew * sr + ((kurtosis - 1) / 4) * sr * sr
    if denom <= 0 or t_obs < 2:
        return {"dsr": 0.0, "sr0_null": round(sr0, 4), "trials": len(trials)}
    stat = (sr - sr0) * math.sqrt(t_obs - 1) / math.sqrt(denom)
    return {"dsr": round(Phi(stat), 4), "sr0_null": round(sr0, 4), "trials": len(trials)}


def moments(daily_rets: list[float]) -> dict:
    n = len(daily_rets)
    mu = sum(daily_rets) / n
    var = sum((r - mu) ** 2 for r in daily_rets) / (n - 1) if n > 1 else 0.0
    if var <= 0:
        return {"skew": 0.0, "kurtosis": 3.0, "n": n}
    sd = math.sqrt(var)
    skew = sum(((r - mu) / sd) ** 3 for r in daily_rets) / n
    kurt = sum(((r - mu) / sd) ** 4 for r in daily_rets) / n
    return {"skew": skew, "kurtosis": kurt, "n": n}
