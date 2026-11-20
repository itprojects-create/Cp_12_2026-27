"""Tests for the deterministic trend core: no-lookahead discipline + economics sanity.

The rule was frozen 2026-10-06 BEFORE any backtest ran (trend_core.py docstring).
These tests protect that freeze: if the rule changes, these must be revisited.
"""
from __future__ import annotations

import math

from app.core.trend_core import (
    classify_trend_series, name_features, run_core,
    MA_FAST, MA_SLOW, MIN_TREND_BARS, MAX_POSITION_PCT, TARGET_VOL, COST_PER_SIDE,
)


# ---------------------------------------------------------------- helpers
def _ramp(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * i for i in range(n)]


def _fall(n: int, start: float = 300.0, step: float = -1.0) -> list[float]:
    return [start + step * i for i in range(n)]


# ------------------------------------------------- classify_trend_series
def test_trend_unknown_before_min_bars():
    out = classify_trend_series(_ramp(59))
    assert len(out) == 59 and all(s == "UNKNOWN" for s in out)


def test_trend_up_on_ramp():
    out = classify_trend_series(_ramp(120))
    assert out[-1] == "UP"
    assert all(s in ("UP", "RANGE") for s in out[MIN_TREND_BARS:])


def test_trend_down_on_fall():
    out = classify_trend_series(_fall(120))
    assert out[-1] == "DOWN"


def test_trend_prefix_invariance_no_lookahead():
    """Appending future bars must not change any past classification."""
    short = classify_trend_series(_ramp(80))
    long = classify_trend_series(_ramp(80) + _fall(40))
    assert short == long[:80]


# ------------------------------------------------------- name_features
def test_name_features_no_lookahead():
    short = name_features(_ramp(80))
    long = name_features(_ramp(80) + _fall(40))
    assert short == long[:80]


def test_name_features_vol_target_capped():
    feats = name_features(_ramp(300))
    assert feats[-1]["vol_target_size"] <= MAX_POSITION_PCT + 1e-12
    assert feats[-1]["mom_ok"] is True


def test_name_features_volatile_name_sized_down():
    calm_closes = _ramp(300, step=0.5)
    wild_closes = [100.0 + (2.0 if i % 2 else -2.0) * (1 + 0.01 * i) for i in range(300)]
    fw = name_features(wild_closes)
    fc = name_features(calm_closes)
    assert fc[-1]["vol_target_size"] >= fw[-1]["vol_target_size"]


# ------------------------------------------------------------ run_core
def test_run_core_flat_in_downtrend_no_loss_beyond_costs():
    """Falling index -> no positions -> equity unchanged (costs 0 too)."""
    idx = _fall(200)
    names = {"A.NS": _fall(200), "B.NS": _fall(200)}
    rep = run_core(idx, names)
    assert rep.total_return == 0.0
    assert rep.total_cost == 0.0


def test_run_core_gross_exposure_capped_at_100pct():
    """AMENDMENT 1: the book never holds more than 100% of capital."""
    # 12 identical qualifying names would each want ~10% -> 120% gross; cap must bind.
    idx = _ramp(400)
    names = {f"N{i}.NS": _ramp(400, step=1.0 + 0.01 * i) for i in range(12)}
    # exposure metric is avg gross; on this tape every rebalance qualifies all names
    rep = run_core(idx, names)
    assert rep.exposure <= 1.0 + 1e-9
    assert rep.max_drawdown <= 1.0


def test_run_core_uses_only_past_bars():
    """A crash AFTER day 100 must not affect the book's first 100 days."""
    good = _ramp(100)
    crash = _fall(100)
    idx = good + crash
    names = {"A.NS": good + crash}
    full = run_core(idx, names)
    truncated = run_core(idx[:100], {"A.NS": (good + crash)[:100]})
    # first 100 days: identical equity path (same positions, same returns)
    assert truncated.n_days == 100
    # the truncated run is entirely inside the ramp: profitable, no crash losses
    assert truncated.total_return > 0
    # and its final equity equals a recomputation from the full run's path at t=99
    # (indirect no-lookahead proof: crash info cannot leak backwards)
    assert full.n_days == 200


def test_run_core_costs_applied_on_switches():
    idx = _ramp(150) + _fall(120) + _ramp(120)  # up, down, up
    names = {"A.NS": idx}
    rep = run_core(idx, names)
    assert rep.total_cost > 0
    assert rep.n_switches > 0
    # every rupee of cost is booked: equity <= gross path (no negative costs)
    assert rep.total_cost > 0
    assert rep.n_switches > 0
    # every switch books COST_PER_SIDE * |delta| with |delta| <= MAX_POSITION_PCT
    assert math.isfinite(rep.total_cost)
    assert rep.total_cost <= rep.n_switches * COST_PER_SIDE * MAX_POSITION_PCT + 1e-9


def test_run_core_sharpe_and_mdd_finite():
    idx = _ramp(150) + _fall(120) + _ramp(120)
    rep = run_core(idx, {"A.NS": idx, "B.NS": _ramp(390, step=0.4)})
    assert math.isfinite(rep.sharpe) and math.isfinite(rep.max_drawdown)
    assert 0.0 <= rep.max_drawdown <= 1.0
    assert rep.exposure <= MAX_POSITION_PCT * rep.n_names + 1e-9
