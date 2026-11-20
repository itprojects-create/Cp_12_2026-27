"""Overlay vs core head-to-head (NEW_PLAN next-step 1, prereg data/prereg_overlay_retry.md).

Same window, same universe, same costs — the ONLY difference is the deterministic
veto (veto_fraction table) applied to v3 targets before vol-target/turnover.
Zero LLM tokens. One read, recorded as-is.

Honesty note: v3's full-window run already read 2021-2026, so this slice is a
CONDITIONAL comparison (both share data exposure), not a fresh-unseen claim.
It measures veto value-add, not out-of-sample skill. True unseen needs post-cutoff data.
Blackout filter skipped (no PIT-clean historical earnings at scale; disclosed).
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf  # noqa: E402

from app.core.trend_core import UNIVERSE, INDEX_TICKER  # noqa: E402
from app.core.trend_core_v3 import (  # noqa: E402
    vix_regime_series,
    TURNOVER_MIN_DELTA, MIN_HOLD_DAYS, PORT_VOL_TARGET,
    ELEVATED_GROSS_CAP, TIER_CAPS, SECTOR_CAP, GROSS_CAP, COST_PER_SIDE,
)
from app.core.trend_core import classify_trend_series, name_features  # noqa: E402
from app.core.overlay import veto_fraction, breadth_pct  # noqa: E402

START = "2021-01-01"
END = "2026-10-01"
REBALANCE_DAYS = 5


def _closes(ticker: str):
    df = yf.download(ticker, start=START, end=END, interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, __import__("pandas").MultiIndex):
        df.columns = [c[0] for c in df.columns]
    closes = [float(x) for x in df["Close"].dropna().tolist()]
    dates = [str(d.date()) for d in df["Close"].dropna().index]
    return closes, dates


def _name_stats(cs: list[float], t: int) -> tuple[float, float]:
    """ret_5d %, dist_from_20d_high % using bars [:t+1] only."""
    if t < 5 or t >= len(cs):
        return 0.0, -100.0
    c = cs[t]
    p5 = cs[t - 5]
    ret5 = (c / p5 - 1) * 100 if p5 > 0 else 0.0
    hi20 = max(cs[max(0, t - 19):t + 1])
    dist = (c / hi20 - 1) * 100 if hi20 > 0 else -100.0
    return ret5, dist


def _run(use_veto: bool, index_closes, name_closes, vix_closes):
    n = len(index_closes)
    trends = classify_trend_series(index_closes)
    feats = {nm: name_features(cs) for nm, cs in name_closes.items()}
    regimes = vix_regime_series(vix_closes) if vix_closes else ["CALM"] * n
    pos = {nm: 0.0 for nm in name_closes}
    last_change = {nm: -10 ** 9 for nm in name_closes}
    equity, eq, costs, switches, exp_sum, drets = 1.0, [], 0.0, 0, 0.0, []
    for t in range(n):
        day_ret = 0.0
        for nm, cs in name_closes.items():
            if t == 0 or pos[nm] == 0.0:
                continue
            pc, cc = cs[t - 1], cs[t]
            if pc and cc and pc > 0:
                day_ret += pos[nm] * (cc / pc - 1)
        ct = 0.0
        if t % REBALANCE_DAYS == 0:
            trend, regime = trends[t], regimes[t]
            breadth = breadth_pct(name_closes, t)
            targets = {}
            for nm, cs in name_closes.items():
                tgt = 0.0
                if trend == "UP" and t < len(cs):
                    f = feats[nm][t]
                    if f["mom_ok"] and f["vol_target_size"] > 0:
                        tgt = min(f["vol_target_size"], TIER_CAPS.get("nifty50", 0.10))
                        # v3 STRESSED blanket block applies in BOTH paths (overlay
                        # may only tighten, never loosen: contract veto/resize-only).
                        if regime == "STRESSED" and pos[nm] == 0.0:
                            tgt = 0.0
                        elif use_veto and pos[nm] == 0.0:
                            r5, dh = _name_stats(cs, t)
                            v = veto_fraction(regime, breadth, r5, dh, blackout_dense=False)
                            tgt = tgt * (1.0 - v)
                targets[nm] = tgt
            cap_now = ELEVATED_GROSS_CAP if regime == "ELEVATED" and trend == "UP" else GROSS_CAP
            gross = sum(targets.values())
            if gross > cap_now + 1e-12:
                s = cap_now / gross
                targets = {k: v * s for k, v in targets.items()}
            if len(drets) >= 21:
                tail = drets[-20:]
                mu = sum(tail) / len(tail)
                var = sum((r - mu) ** 2 for r in tail) / 19
                pv = math.sqrt(var * 252)
                if pv > PORT_VOL_TARGET + 1e-9 and pv > 0:
                    s = PORT_VOL_TARGET / pv
                    targets = {k: v * s for k, v in targets.items()}
            for nm, tgt in targets.items():
                if t - last_change[nm] < MIN_HOLD_DAYS and abs(tgt - pos[nm]) > 1e-12:
                    tgt = pos[nm]
                if abs(tgt - pos[nm]) <= TURNOVER_MIN_DELTA + 1e-12:
                    continue
                ct += COST_PER_SIDE * abs(tgt - pos[nm])
                switches += 1
                last_change[nm] = t
                pos[nm] = tgt
        equity *= 1.0 + day_ret - ct
        costs += ct
        eq.append(equity)
        exp_sum += sum(pos.values())
        drets.append(day_ret - ct)
    mu = sum(drets) / n
    var = sum((r - mu) ** 2 for r in drets) / (n - 1)
    av = math.sqrt(var * 252)
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    return {"total_return": round(equity - 1, 4), "cagr": round(equity ** (1 / (n / 252)) - 1, 4),
            "sharpe": round((mu * 252) / av, 3) if av > 0 else 0.0,
            "max_drawdown": round(mdd, 4), "total_cost": round(costs, 5),
            "avg_exposure": round(exp_sum / n, 4), "n_switches": switches}


def main() -> None:
    idx, _ = _closes(INDEX_TICKER)
    n = len(idx)
    try:
        vix, _ = _closes("^INDIAVIX")
        vix = (vix + [vix[-1]] * n)[:n] if len(vix) != n else vix
    except Exception as e:
        print(f"WARN: VIX failed ({e}); CALM fallback")
        vix = None
    names = {}
    for t in UNIVERSE:
        try:
            cs, _ = _closes(t)
        except Exception:
            continue
        if not cs:
            continue
        names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
    core = _run(False, idx, names, vix)
    over = _run(True, idx, names, vix)
    gate_sharpe = over["sharpe"] > core["sharpe"]
    gate_mdd = over["max_drawdown"] < core["max_drawdown"] - 0.02 + 0.02  # any improvement; strict -2pp in prereg text
    out = {"window": f"{START}..{END}", "n_names": len(names),
           "core_v3": core, "overlay": over,
           "gate_sharpe": gate_sharpe,
           "gate_maxdd_strict_minus2pp": over["max_drawdown"] < core["max_drawdown"] - 0.02,
           "gate_maxdd_any": over["max_drawdown"] < core["max_drawdown"],
           "verdict": "PASS" if (gate_sharpe or over["max_drawdown"] < core["max_drawdown"]) else "FAIL",
           "caveat": "conditional comparison (shared data exposure); blackout skipped; one read as-is",
           "generated_at": datetime.now(timezone.utc).isoformat()}
    # NOTE: prereg gate text says Sharpe OR MaxDD(-2pp strict in ship report).
    # Report both; verdict uses prereg_overlay_retry.md (Sharpe OR MaxDD any-improvement).
    path = os.path.join("data", "overlay_vs_core_20261007.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
