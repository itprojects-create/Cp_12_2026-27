"""One-shot walk-forward backtest of the FROZEN trend core over 2021-2026.

Zero LLM tokens. Data via yfinance (auto_adjust=True total return). This script
RUNS the frozen rule — it does not tune it. Whatever comes out is recorded.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf  # noqa: E402

from app.core.trend_core import UNIVERSE, INDEX_TICKER, run_core  # noqa: E402

START = "2021-01-01"
END = "2026-10-01"


def _closes(ticker: str) -> tuple[list[float], list[str]]:
    df = yf.download(ticker, start=START, end=END, interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, __import__("pandas").MultiIndex):
        df.columns = [c[0] for c in df.columns]
    closes = [float(x) for x in df["Close"].dropna().tolist()]
    dates = [str(d.date()) for d in df["Close"].dropna().index]
    return closes, dates


def main() -> None:
    idx_closes, dates = _closes(INDEX_TICKER)
    n = len(idx_closes)
    name_closes: dict[str, list[float]] = {}
    for t in UNIVERSE:
        try:
            cs, _ = _closes(t)
        except Exception as e:
            print(f"WARN: {t} fetch failed ({e}); excluded (disclosed in report)")
            continue
        if len(cs) < n * 0.9:  # tolerate a few missing bars by padding flat
            cs = cs + [cs[-1]] * (n - len(cs)) if cs else cs
        if len(cs) != n:
            cs = (cs + [cs[-1]] * n)[:n] if cs else cs
        if cs:
            name_closes[t] = cs
    print(f"index bars: {n} ({dates[0]}..{dates[-1]}), names: {len(name_closes)}/{len(UNIVERSE)}")

    rep = run_core(idx_closes, name_closes)

    # Fair risk-adjusted comparison: equal-weight B&H curve stats on same bars.
    import math as _m
    bench_curve, bench_val = [], 1.0
    bench_daily = []
    for t in range(1, n):
        r = sum((cs[t] / cs[t - 1] - 1) / len(name_closes)
                for cs in name_closes.values() if t < len(cs) and cs[t - 1] > 0)
        bench_val *= 1 + r
        bench_curve.append(bench_val)
        bench_daily.append(r)
    bpeak, bmdd = (bench_curve[0] if bench_curve else 1.0), 0.0
    for v in bench_curve:
        bpeak = max(bpeak, v)
        if bpeak > 0:
            bmdd = max(bmdd, 1 - v / bpeak)
    bmu = sum(bench_daily) / len(bench_daily)
    bvar = sum((x - bmu) ** 2 for x in bench_daily) / (len(bench_daily) - 1)
    bench_sharpe = (bmu * 252) / (_m.sqrt(bvar * 252)) if bvar > 0 else 0.0

    # Diagnostic (report-only, rule untouched): where did the core bleed vs B&H?
    # Not used for any tuning — the rule stays frozen. Informs the overlay design.
    eq = rep.eq_curve
    yearly = {}
    for t in range(0, n, 1):
        yr = dates[t][:4]
        yearly.setdefault(yr, {"start_eq": None, "end_eq": eq[t], "peak": eq[t], "trough": eq[t]})
        y = yearly[yr]
        if y["start_eq"] is None:
            y["start_eq"] = eq[t - 1] if t > 0 else 1.0
        y["end_eq"] = eq[t]
        y["peak"] = max(y["peak"], eq[t])
        y["trough"] = min(y["trough"], eq[t])
    yearly_out = {yr: {
        "ret": round(v["end_eq"] / v["start_eq"] - 1, 4),
        "intra_yr_dd": round(v["trough"] / v["peak"] - 1, 4)}
        for yr, v in yearly.items()}

    out = {
        "frozen_rule": "app/core/trend_core.py (frozen 2026-10-06 before this run)",
        "window": f"{dates[0]}..{dates[-1]}",
        "start": dates[0], "end": dates[-1],
        "n_days": rep.n_days, "n_names": rep.n_names,
        "excluded_names": sorted(set(UNIVERSE) - set(name_closes)),
        "total_return": round(rep.total_return, 4),
        "cagr": round(rep.cagr, 4),
        "ann_vol": round(rep.ann_vol, 4),
        "sharpe": round(rep.sharpe, 3),
        "max_drawdown": round(rep.max_drawdown, 4),
        "total_cost": round(rep.total_cost, 5),
        "avg_exposure": round(rep.exposure, 4),
        "n_switches": rep.n_switches,
        "yearly_diagnostic": yearly_out,
        "bench_eqw_buyhold_cagr": round(rep.bench_cagr, 4),
        "bench_eqw_buyhold_max_drawdown": round(bmdd, 4),
        "bench_eqw_buyhold_sharpe": round(bench_sharpe, 3),
        "survivorship_caveat": "universe = 2026 NIFTY members that existed pre-2021; result is biased UP; overlay must beat core despite that",
        "cost_model": "0.105% per side on |delta position| (ROUNDTRIP_COST/2)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join("data", "core_backtest_20261006.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k not in ("frozen_rule",)}, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
