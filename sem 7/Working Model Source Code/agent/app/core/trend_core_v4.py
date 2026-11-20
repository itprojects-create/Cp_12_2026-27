"""Trend core v4: v3 filters + top-K selection + baked veto + bench correction.

Prereg: data/prereg_core_v4.md (written before any v4 run). v2/v3 modules
untouched — classifiers and veto table reused, never re-tuned.

Pipeline at each rebalance (PIT-clean, bars [:t+1] only):
  qualifiers (UP + mom>0 + vol>0, minus STRESSED-new/blackout-new)
  -> rank by 60d momentum -> top K=50
  -> vol-size + tier cap -> sector cap -> gross cap
  -> veto new entries (shrink-only) -> vol-target (down-only) -> turnover/min-hold
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field  # noqa: F401 (report-shape parity with v3)

from app.core.trend_core import (
    classify_trend_series,
    name_features,
    CoreReport,
    REBALANCE_DAYS,
    MAX_POSITION_PCT,
    GROSS_CAP,
    COST_PER_SIDE,
)
from app.core.trend_core_v3 import (
    vix_regime_series,
    TURNOVER_MIN_DELTA,
    MIN_HOLD_DAYS,
    BLACKOUT_DAYS,
    PORT_VOL_TARGET,
    ELEVATED_GROSS_CAP,
    TIER_CAPS,
    SECTOR_CAP,
)
from app.core.overlay import veto_fraction, breadth_pct

TOP_K = 50
MOMENTUM_LOOKBACK = 60


def _mom60(cs: list[float], t: int) -> float:
    if t < MOMENTUM_LOOKBACK or t >= len(cs) or cs[t - MOMENTUM_LOOKBACK] <= 0:
        return float("-inf")
    return cs[t] / cs[t - MOMENTUM_LOOKBACK] - 1


def _name_stats(cs: list[float], t: int) -> tuple[float, float]:
    if t < 5 or t >= len(cs):
        return 0.0, -100.0
    c = cs[t]
    p5 = cs[t - 5]
    ret5 = (c / p5 - 1) * 100 if p5 > 0 else 0.0
    hi20 = max(cs[max(0, t - 19):t + 1])
    dist = (c / hi20 - 1) * 100 if hi20 > 0 else -100.0
    return ret5, dist


def bench_cagr_corrected(name_closes: dict[str, list[float]], n_days: int) -> float:
    """Equal-weight buy&hold CAGR, corrected math (prereg v4).

    bench_total = mean of individual total returns; CAGR from that.
    v2/v3 used prod(1 + ret_i/N), which explodes with N (119.9% artifact).
    """
    rets = []
    for cs in name_closes.values():
        if len(cs) > 1 and cs[0] > 0:
            rets.append(cs[-1] / cs[0] - 1)
    if not rets:
        return 0.0
    total = sum(rets) / len(rets)
    years = n_days / 252.0
    return ((1 + total) ** (1 / years) - 1) if total > -1 and years > 0 else -1.0


def run_core_v4(index_closes: list[float], name_closes: dict[str, list[float]],
                vix_closes: list[float] | None = None,
                blackout: dict[str, set[int]] | None = None,
                tier: dict[str, str] | None = None,
                sector: dict[str, str] | None = None,
                dates: list[str] | None = None,
                membership_fn=None,
                membership_log: list | None = None,
                entry_gate_fn=None) -> CoreReport:
    """membership_fn (optional, P0): date_iso -> snapshot dict {members, pit_status,
    membership_hash} from pit_membership.membership_at. When supplied WITH dates,
    each rebalance filters to PIT members (ineligible names exit via target 0,
    turnover gates still apply); UNKNOWN snapshots freeze the rebalance (no
    changes — abstention, never liquidation on unverified data). Default
    None = legacy static-universe behavior, byte-identical (all existing tests).
    membership_log (optional out-param) receives per-rebalance audit dicts.
    entry_gate_fn (optional, P3): (name, bar, date_or_None) -> True to ALLOW a
    new entry. Called only for new entries alongside the existing veto; a False
    vetoes the entry (shrink-only event blackout with per-bar PIT eligibility).
    Default None = legacy behavior, byte-identical."""
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
        # P0 PIT membership: resolve BEFORE the rebalance gate so UNKNOWN can freeze.
        pit_members = None
        pit_frozen = False
        pit_hash = ""
        pit_status = "STATIC"
        if (membership_fn is not None and dates is not None and t < len(dates)
                and t % REBALANCE_DAYS == 0):
            snap = membership_fn(dates[t])
            pit_hash = str(snap.get("membership_hash", ""))
            pit_status = str(snap.get("pit_status", "UNKNOWN"))
            if pit_status == "UNKNOWN":
                pit_frozen = True  # abstain from changes on unverified data
            else:
                pit_members = set(snap.get("members", ()))
        if membership_log is not None and t % REBALANCE_DAYS == 0:
            membership_log.append({
                "bar": t, "date": dates[t] if dates and t < len(dates) else f"bar-{t}",
                "pit_status": pit_status, "membership_hash": pit_hash,
                "n_eligible": len(pit_members) if pit_members is not None else len(name_closes),
                "frozen": pit_frozen})
        if t % REBALANCE_DAYS == 0 and not pit_frozen:
            trend = trends[t]
            regime = regimes[t] if t < len(regimes) else "CALM"
            breadth = breadth_pct(name_closes, t)
            # 1) qualify + rank by 60d momentum -> top-K
            ranked: list[tuple[float, str]] = []
            for nm, cs in name_closes.items():
                if pit_members is not None and nm not in pit_members:
                    continue  # not a member at this rebalance — invisible, never ranked
                if trend != "UP" or t >= len(cs):
                    continue
                f = feats[nm][t]
                if not (f["mom_ok"] and f["vol_target_size"] > 0):
                    continue
                if regime == "STRESSED" and pos[nm] == 0.0:
                    continue  # v3 blanket block (veto may only tighten further)
                bl = blackout.get(nm, set())
                if pos[nm] == 0.0 and any(0 <= (b - t) <= BLACKOUT_DAYS for b in bl):
                    continue
                if pos[nm] == 0.0 and entry_gate_fn is not None:
                    date_t = dates[t] if dates is not None and t < len(dates) else None
                    if entry_gate_fn(nm, t, date_t) is False:
                        continue  # P3 event-blackout entry veto (shrink-only)
                ranked.append((_mom60(cs, t), nm))
            ranked.sort(key=lambda x: x[0], reverse=True)
            selected = {nm for _, nm in ranked[:TOP_K]}
            # 2) size + tier cap
            targets: dict[str, float] = {}
            for nm, cs in name_closes.items():
                target = 0.0
                if pit_members is not None and nm not in pit_members:
                    targets[nm] = 0.0  # exited names liquidate via target 0
                    continue
                if nm in selected:
                    f = feats[nm][t]
                    cap = TIER_CAPS.get(tier.get(nm, "nifty50"), MAX_POSITION_PCT)
                    target = min(f["vol_target_size"], cap)
                    if pos[nm] == 0.0:  # veto: new entries only, shrink-only
                        r5, dh = _name_stats(cs, t)
                        v = veto_fraction(regime, breadth, r5, dh, blackout_dense=False)
                        shrunk = target * (1.0 - v)
                        assert shrunk <= target + 1e-12
                        target = shrunk
                targets[nm] = target
            # 3) sector cap 25%
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
            # 4) gross caps
            cap_now = ELEVATED_GROSS_CAP if regime == "ELEVATED" and trend == "UP" else GROSS_CAP
            gross = sum(targets.values())
            if gross > cap_now + 1e-12:
                scale = cap_now / gross
                targets = {nm_: v_ * scale for nm_, v_ in targets.items()}
            # 5) vol target (down-only)
            if len(daily_rets) >= 21:
                tail = daily_rets[-20:]
                mu = sum(tail) / len(tail)
                var = sum((r - mu) ** 2 for r in tail) / (len(tail) - 1)
                pv = math.sqrt(var * 252)
                if pv > PORT_VOL_TARGET + 1e-9 and pv > 0:
                    s = PORT_VOL_TARGET / pv
                    targets = {nm_: v_ * s for nm_, v_ in targets.items()}
            # 6) turnover + min-hold
            for nm, target in targets.items():
                if t - last_change[nm] < MIN_HOLD_DAYS and abs(target - pos[nm]) > 1e-12:
                    target = pos[nm]
                if abs(target - pos[nm]) <= TURNOVER_MIN_DELTA + 1e-12:
                    continue
                cost_today += COST_PER_SIDE * abs(target - pos[nm])
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

    return CoreReport(
        n_days=n, n_names=len(name_closes), total_return=equity - 1, cagr=cagr,
        ann_vol=ann_vol, sharpe=sharpe, max_drawdown=mdd, total_cost=cost_total,
        exposure=exposure_sum / n, n_switches=switches,
        bench_cagr=bench_cagr_corrected(name_closes, n),
        eq_curve=eq_curve,
    )
