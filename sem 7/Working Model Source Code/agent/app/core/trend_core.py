"""Deterministic trend core: long/flat NIFTY-50 names on the index's own trend.

THE PROFIT ENGINE (owner decision 2026-10-06): the measured evidence says the LLM
pipeline has no directional skill (0/11 runs beat a constant rule) while the
trend-conditioned constant does (0.58-0.62 accuracy). So direction is owned by
deterministic code; the LLM may later only VETO or RESIZE this core's trades
(pre-registered overlay contract before the overlay is ever evaluated).

RULE (frozen 2026-10-06, BEFORE any backtest was run — same discipline as
app/eval/gates.py; do not tune after seeing results).
AMENDMENT 1 (preregistered in data/prereg_core_v2_exposure.md, 2026-10-06, after
the v1 run exposed the exposure bug): GROSS_CAP=1.00 — the book never holds more
than 100% of capital; qualifying positions are scaled proportionally if the
frozen per-name rule sums above that. This makes the code match the written
rule ("fractions of book"); it is a correction, not a re-tune.
  At each rebalance date t (every REBALANCE_DAYS trading days):
    trend[t] = UP   iff NIFTY close[t] > MA50[t] and MA20[t] > MA50[t]
             DOWN   iff close[t] < MA50[t] and MA20[t] < MA50[t]
             RANGE/UNKNOWN otherwise (incl. < MIN_TREND_BARS history)
    name i position (fraction of book, long/flat only):
      trend[t] != UP                -> 0.0        (index not trending up: no edge, stay flat)
      name 60d return <= 0          -> 0.0        (skip falling knives even in up tapes)
      else vol-targeted size = min(MAX_POSITION_PCT, TARGET_VOL / ann_vol_20d[i][t])
  Between rebalances positions are held (drift with prices), no intraweek trades.
  Costs: ROUNDTRIP_COST/2 per side on every |change in position|.

PIT discipline: every feature at t uses data up to and INCLUDING t's close
(decision executed at t's close; return accrues t->t+1). shift() discipline is
tested in tests/test_core.py. No future bar enters any feature.

Honest limitations (disclosed up front, never hidden):
- Survivorship bias: the universe is NIFTY members as of 2026 that were members
  in 2021 too (plus TATAMOTORS through its 2025 demerger). This INFLATES the
  core's result; the overlay must beat the core despite that.
- auto_adjust=True (total-return, split/dividend-corrected) — deliberately
  different from the agent feed's auto_adjust=False: backtests must use total
  return or costs/returns are both wrong.
- 2021-2026 is one tape; the rule is a priori, not fitted — but a single regime
  mix. The 2022 chop is inside the window as an out-of-regime check.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.data.base import ROUNDTRIP_COST

REBALANCE_DAYS = 5
MA_FAST, MA_SLOW = 20, 50
MIN_TREND_BARS = 60          # same conservative floor as classify_trend()
MOMENTUM_LOOKBACK = 60       # name's own 60d return filter
VOL_LOOKBACK = 20
TARGET_VOL = 0.12            # 12% annualized per-name vol target
MAX_POSITION_PCT = 0.10      # same cap as the agent pipeline
GROSS_CAP = 1.00             # AMENDMENT 1: Σ positions ≤ 100% of book (preregistered)
COST_PER_SIDE = ROUNDTRIP_COST / 2.0

# Long-standing NIFTY members (member well before 2021 and still members at
# build time), + TATAMOTORS kept through its 2025-10 demerger (series ends;
# handled as flat). Deliberately includes known 2021-2026 underperformers
# (WIPRO, INDUSINDBK, ONGC) to weaken survivorship.
UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS", "LT.NS", "ITC.NS",
    "BHARTIARTL.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS", "HINDUNILVR.NS",
    "ULTRACEMCO.NS", "NTPC.NS", "POWERGRID.NS", "ONGC.NS", "COALINDIA.NS",
    "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "BAJFINANCE.NS", "ASIANPAINT.NS",
    "GRASIM.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "HINDALCO.NS", "CIPLA.NS",
    "DRREDDY.NS", "EICHERMOT.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS",
    "INDUSINDBK.NS", "ADANIENT.NS", "TATAMOTORS.NS",
]
INDEX_TICKER = "^NSEI"


def classify_trend_series(closes: "list[float]") -> "list[str]":
    """Per-bar UP/DOWN/RANGE/UNKNOWN on a close series. Bar i uses closes[:i+1] only."""
    out: list[str] = []
    for i in range(len(closes)):
        if i + 1 < MIN_TREND_BARS:
            out.append("UNKNOWN")
            continue
        window = closes[: i + 1]
        close = window[-1]
        ma20 = sum(window[-MA_FAST:]) / MA_FAST
        ma50 = sum(window[-MA_SLOW:]) / MA_SLOW
        if close < ma50 and ma20 < ma50:
            out.append("DOWN")
        elif close > ma50 and ma20 > ma50:
            out.append("UP")
        else:
            out.append("RANGE")
    return out


def name_features(closes: "list[float]") -> "list[dict]":
    """Per-bar momentum + realized vol for one name. Bar i uses closes[:i+1] only."""
    out: list[dict] = []
    for i in range(len(closes)):
        f = {"mom_ok": False, "vol_target_size": 0.0}
        if i + 1 > MOMENTUM_LOOKBACK:
            f["mom_ok"] = closes[i] / closes[i - MOMENTUM_LOOKBACK] - 1 > 0
        if i + 1 > VOL_LOOKBACK + 1:
            rets = [closes[j] / closes[j - 1] - 1 for j in range(i - VOL_LOOKBACK + 1, i + 1)]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            ann_vol = math.sqrt(var * 252)
            if ann_vol > 0:
                f["vol_target_size"] = min(MAX_POSITION_PCT, TARGET_VOL / ann_vol)
        out.append(f)
    return out


@dataclass
class CoreReport:
    n_days: int
    n_names: int
    total_return: float
    cagr: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    total_cost: float
    exposure: float
    n_switches: int
    bench_cagr: float = 0.0   # equal-weight buy&hold, same survivorship caveat
    yearly: dict = field(default_factory=dict)
    eq_curve: list = field(default_factory=list)  # diagnostic only, not part of the rule


def run_core(index_closes: "list[float]", name_closes: "dict[str, list[float]]") -> CoreReport:
    """Backtest the frozen rule over aligned daily closes.

    All series are date-aligned by the caller (index dates as the calendar;
    missing name bars -> position 0 for that bar, honestly flat).
    """
    n = len(index_closes)
    trends = classify_trend_series(index_closes)
    feats = {nm: name_features(cs) for nm, cs in name_closes.items()}

    pos = {nm: 0.0 for nm in name_closes}
    equity = 1.0
    eq_curve: list[float] = []
    cost_total = 0.0
    switches = 0
    exposure_sum = 0.0
    daily_rets: list[float] = []

    for t in range(n):
        # 1) accrue yesterday's positions over today's return
        day_ret = 0.0
        for nm, cs in name_closes.items():
            if t == 0 or pos[nm] == 0.0:
                continue
            prev_close = cs[t - 1] if t - 1 < len(cs) else None
            cur_close = cs[t] if t < len(cs) else None
            if prev_close is None or cur_close is None or prev_close <= 0:
                continue  # data hole: honestly flat for this bar
            day_ret += pos[nm] * (cur_close / prev_close - 1)
        cost_today = 0.0
        # 2) rebalance only on the schedule (and once at t=0 to enter)
        if t % REBALANCE_DAYS == 0:
            trend = trends[t]
            targets: dict[str, float] = {}
            for nm, cs in name_closes.items():
                target = 0.0
                if trend == "UP" and t < len(cs):
                    f = feats[nm][t]
                    if f["mom_ok"] and f["vol_target_size"] > 0:
                        target = f["vol_target_size"]
                targets[nm] = target
            # AMENDMENT 1 (preregistered): normalize gross exposure to ≤ GROSS_CAP.
            gross = sum(targets.values())
            if gross > GROSS_CAP + 1e-12:
                scale = GROSS_CAP / gross
                targets = {nm: v * scale for nm, v in targets.items()}
            for nm, target in targets.items():
                delta = abs(target - pos[nm])
                if delta > 1e-9:
                    cost_today += COST_PER_SIDE * delta
                    switches += 1
                pos[nm] = target
        equity *= (1.0 + day_ret - cost_today)
        cost_total += cost_today
        eq_curve.append(equity)
        exposure_sum += sum(pos.values())
        daily_rets.append(day_ret - cost_today)

    years = n / 252.0
    cagr = (equity ** (1 / years) - 1) if equity > 0 and years > 0 else -1.0
    mean_r = sum(daily_rets) / n
    var_r = sum((r - mean_r) ** 2 for r in daily_rets) / (n - 1) if n > 1 else 0.0
    ann_vol = math.sqrt(var_r * 252)
    sharpe = (mean_r * 252) / ann_vol if ann_vol > 0 else 0.0
    peak, mdd = (eq_curve[0] if eq_curve else 1.0), 0.0
    for v in eq_curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, 1 - v / peak)
    # equal-weight buy&hold benchmark on the same (biased) universe
    bench = 1.0
    for cs in name_closes.values():
        if len(cs) > 1 and cs[0] > 0:
            bench *= 1 + (cs[-1] / cs[0] - 1) / len(name_closes)
    bench_cagr = (bench ** (1 / years) - 1) if bench > 0 and years > 0 else -1.0

    return CoreReport(
        n_days=n, n_names=len(name_closes), total_return=equity - 1, cagr=cagr,
        ann_vol=ann_vol, sharpe=sharpe, max_drawdown=mdd, total_cost=cost_total,
        exposure=exposure_sum / n, n_switches=switches, bench_cagr=bench_cagr,
        eq_curve=eq_curve,
    )
