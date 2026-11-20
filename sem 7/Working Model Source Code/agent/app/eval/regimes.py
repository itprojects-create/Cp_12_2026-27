"""Regime analysis: per-regime performance with PIT-safe labels (§22).

Labels are supplied by the caller as {bar_index: regime} using ONLY information
available at that bar (caller contract — the module never looks ahead; it only
groups). Regimes: HIGH_VOL/LOW_VOL/UP_TREND/DOWN_TREND/HIGH_BREADTH/
LOW_BREADTH/STRESS/NORMAL. Intentionally regime-specific strategies must say so.
"""
from __future__ import annotations

from app.eval import stats as S

KNOWN_REGIMES = ("HIGH_VOL", "LOW_VOL", "UP_TREND", "DOWN_TREND",
                 "HIGH_BREADTH", "LOW_BREADTH", "STRESS", "NORMAL")


def analyze(daily: list[float], labels: dict[int, str]) -> dict:
    buckets: dict[str, list[float]] = {r: [] for r in KNOWN_REGIMES}
    unlabeled = 0
    for i, r in enumerate(daily):
        lab = labels.get(i)
        if lab in buckets:
            buckets[lab].append(r)
        else:
            unlabeled += 1
    per_regime = {}
    for regime, rs in buckets.items():
        if not rs:
            continue
        per_regime[regime] = {"n": len(rs), "total": round(sum(rs), 6),
                              "sharpe": round(S.sharpe(rs), 4),
                              "cvar": round(S.cvar(rs), 6)}
    return {"per_regime": per_regime, "unlabeled_bars": unlabeled,
            "n_regimes_present": len(per_regime),
            "single_regime": len(per_regime) == 1}


def regime_dependence(per_regime_report: dict) -> dict:
    """Share of total return earned in the single best regime."""
    pr = per_regime_report.get("per_regime", {})
    totals = {k: v["total"] for k, v in pr.items()}
    grand = sum(totals.values())
    if not totals or not grand:
        return {"best_regime": None, "best_share": 0.0}
    best = max(totals, key=totals.get)
    return {"best_regime": best, "best_share": round(totals[best] / grand, 4)}
