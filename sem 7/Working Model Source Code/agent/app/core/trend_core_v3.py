"""Trend core v3: v2 rule + preregistered risk filters (data/prereg_core_v3.md).

v2 file (`trend_core.py`) is untouched — this module reuses its classifiers
and per-name features, then applies the five v3 filters. All filters are
PIT-clean (bars [:t+1] only) and never create positions, only block/scale.

Filters:
1. VIX regime: STRESSED+UP => no NEW entries; ELEVATED+UP => gross cap 0.50.
2. Turnover: |delta|<=0.015 => hold; min 20d hold per name.
3. Earnings blackout: no NEW entries within 10 trading days pre-result.
4. Portfolio vol target: scale gross down to 10% ann vol (never up).
5. Tier + sector caps: 10% / 5% / 3% per tier, 25% per sector.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.core.trend_core import (
    classify_trend_series,
    name_features,
    CoreReport,
    REBALANCE_DAYS,
    MAX_POSITION_PCT,
    GROSS_CAP,
    COST_PER_SIDE,
)
from app.data.base import ROUNDTRIP_COST  # noqa: F401 (cost source documented)

TURNOVER_MIN_DELTA = 0.015
MIN_HOLD_DAYS = 20
BLACKOUT_DAYS = 10
PORT_VOL_TARGET = 0.10
ELEVATED_GROSS_CAP = 0.50
TIER_CAPS = {"nifty50": 0.10, "nifty500": 0.05, "sme": 0.03}
SECTOR_CAP = 0.25


def vix_regime_series(vix_closes: list[float], lookback: int = 252) -> list[str]:
    """Trailing-percentile VIX regime per bar. Bar i uses closes[:i+1] only.

    pct = % of trailing bars (strictly before i) with VIX < current.
    <60 bars history => CALM (conservative default, same as app/data/regime.py).
    """
    out: list[str] = []
    for i in range(len(vix_closes)):
        hist = vix_closes[max(0, i - lookback):i]
        if len(hist) < 60:
            out.append("CALM")
            continue
        cur = vix_closes[i]
        pct = sum(1 for v in hist if v < cur) / len(hist) * 100
        if pct >= 85.0:
            out.append("STRESSED")
        elif pct >= 50.0:
            out.append("ELEVATED")
        else:
            out.append("CALM")
    return out


def run_core_v3(index_closes: list[float], name_closes: dict[str, list[float]],
                vix_closes: list[float] | None = None,
                blackout: dict[str, set[int]] | None = None,
                tier: dict[str, str] | None = None,
                sector: dict[str, str] | None = None) -> CoreReport:
    n = len(index_closes)
    trends = classify_trend_series(index_closes)
    feats = {nm: name_features(cs) for nm, cs in name_closes.items()}
    regimes = vix_regime_series(vix_closes) if vix_closes else ["CALM"] * n
    blackout = blackout or {}
    tier = tier or {}
    sector = sector or {}

    pos = {nm: 0.0 for nm in name_closes}
    last_change = {nm: -10 ** 9 for nm in name_closes}
    equity = 1.0
    eq_curve: list[float] = []
    cost_total = 0.0
    switches = 0
    exposure_sum = 0.0
    daily_rets: list[float] = []

    for t in range(n):
        day_ret = 0.0
        for nm, cs in name_closes.items():
            if t == 0 or pos[nm] == 0.0:
                continue
            prev_close = cs[t - 1] if t - 1 < len(cs) else None
            cur_close = cs[t] if t < len(cs) else None
            if prev_close is None or cur_close is None or prev_close <= 0:
                continue
            day_ret += pos[nm] * (cur_close / prev_close - 1)
        cost_today = 0.0
        if t % REBALANCE_DAYS == 0:
            trend = trends[t]
            regime = regimes[t] if t < len(regimes) else "CALM"
            targets: dict[str, float] = {}
            for nm, cs in name_closes.items():
                target = 0.0
                if trend == "UP" and t < len(cs):
                    f = feats[nm][t]
                    if f["mom_ok"] and f["vol_target_size"] > 0:
                        target = f["vol_target_size"]
                        # Tier cap (default = legacy 10%)
                        cap = TIER_CAPS.get(tier.get(nm, "nifty50"), MAX_POSITION_PCT)
                        target = min(target, cap)
                        # Earnings blackout: block NEW entries only
                        bl = blackout.get(nm, set())
                        in_blackout = any(0 <= (b - t) <= BLACKOUT_DAYS for b in bl)
                        if in_blackout and pos[nm] == 0.0:
                            target = 0.0
                        # STRESSED: block NEW entries; holds pass
                        if regime == "STRESSED" and pos[nm] == 0.0:
                            target = 0.0
                targets[nm] = target
            # Sector cap 25% (proportional within breaching sector)
            if sector:
                by_sec: dict[str, list[str]] = {}
                for nm in targets:
                    by_sec.setdefault(sector.get(nm, "UNKNOWN"), []).append(nm)
                for names in by_sec.values():
                    gross_s = sum(targets[nm] for nm in names)
                    if gross_s > SECTOR_CAP + 1e-12:
                        scale = SECTOR_CAP / gross_s
                        for nm in names:
                            targets[nm] *= scale
            # Gross caps: v2 1.00 always; ELEVATED 0.50 tighter
            cap_now = ELEVATED_GROSS_CAP if regime == "ELEVATED" and trend == "UP" else GROSS_CAP
            gross = sum(targets.values())
            if gross > cap_now + 1e-12:
                scale = cap_now / gross
                targets = {nm: v * scale for nm, v in targets.items()}
            # Portfolio vol target (scale down only): trailing 20d port vol
            if len(daily_rets) >= 21:
                tail = daily_rets[-20:]
                mu = sum(tail) / len(tail)
                var = sum((r - mu) ** 2 for r in tail) / (len(tail) - 1)
                pv = math.sqrt(var * 252)
                if pv > PORT_VOL_TARGET + 1e-9 and pv > 0:
                    s = PORT_VOL_TARGET / pv
                    targets = {nm: v * s for nm, v in targets.items()}
            # Turnover + min-hold: apply per name
            for nm, target in targets.items():
                if t - last_change[nm] < MIN_HOLD_DAYS and abs(target - pos[nm]) > 1e-12:
                    target = pos[nm]  # hold: too soon to flip
                delta = abs(target - pos[nm])
                if delta <= TURNOVER_MIN_DELTA + 1e-12:
                    continue  # dust: hold, no cost
                if delta > 1e-9:
                    cost_today += COST_PER_SIDE * delta
                    switches += 1
                    last_change[nm] = t
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
