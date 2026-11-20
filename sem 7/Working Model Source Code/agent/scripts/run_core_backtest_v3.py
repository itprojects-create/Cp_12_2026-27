"""One-shot v3 backtest (NEW_PLAN Day 3, prereg data/prereg_core_v3.md).

Same window/universe as v2 for comparability. Zero LLM tokens.
VIX series (^INDIAVIX) aligned to index calendar; missing VIX bars => CALM.
Earnings blackout: not available PIT-clean historically at scale => skipped
with disclosure (filter tested synthetically in test_core_v3.py).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf  # noqa: E402

from app.core.trend_core import UNIVERSE, INDEX_TICKER  # noqa: E402
from app.core.trend_core_v3 import run_core_v3  # noqa: E402

START = "2021-01-01"
END = "2026-10-01"


def _closes(ticker: str):
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
    try:
        vix_closes, _ = _closes("^INDIAVIX")
        if len(vix_closes) != n:
            vix_closes = (vix_closes + [vix_closes[-1]] * n)[:n] if vix_closes else None
    except Exception as e:
        print(f"WARN: VIX fetch failed ({e}); v3 runs as CALM (disclosed)")
        vix_closes = None
    name_closes: dict[str, list[float]] = {}
    for t in UNIVERSE:
        try:
            cs, _ = _closes(t)
        except Exception as e:
            print(f"WARN: {t} fetch failed ({e}); excluded")
            continue
        if len(cs) != n:
            cs = (cs + [cs[-1]] * n)[:n] if cs else cs
        if cs:
            name_closes[t] = cs
    print(f"index bars: {n}, names: {len(name_closes)}/{len(UNIVERSE)}, vix: {'ok' if vix_closes else 'CALM-fallback'}")
    rep = run_core_v3(idx_closes, name_closes, vix_closes=vix_closes)
    eq = rep.eq_curve
    yearly = {}
    for t in range(n):
        yr = dates[t][:4]
        yearly.setdefault(yr, {"start_eq": None, "end_eq": eq[t], "peak": eq[t], "trough": eq[t]})
        y = yearly[yr]
        if y["start_eq"] is None:
            y["start_eq"] = eq[t - 1] if t > 0 else 1.0
        y["end_eq"] = eq[t]
        y["peak"] = max(y["peak"], eq[t])
        y["trough"] = min(y["trough"], eq[t])
    yearly_out = {yr: {"ret": round(v["end_eq"] / v["start_eq"] - 1, 4),
                       "intra_yr_dd": round(v["trough"] / v["peak"] - 1, 4)} for yr, v in yearly.items()}
    out = {
        "frozen_rule": "app/core/trend_core_v3.py (prereg data/prereg_core_v3.md, one run)",
        "base": "v2 app/core/trend_core.py untouched",
        "window": f"{dates[0]}..{dates[-1]}",
        "n_days": rep.n_days, "n_names": rep.n_names,
        "excluded_names": sorted(set(UNIVERSE) - set(name_closes)),
        "total_return": round(rep.total_return, 4), "cagr": round(rep.cagr, 4),
        "ann_vol": round(rep.ann_vol, 4), "sharpe": round(rep.sharpe, 3),
        "max_drawdown": round(rep.max_drawdown, 4),
        "total_cost": round(rep.total_cost, 5),
        "avg_exposure": round(rep.exposure, 4), "n_switches": rep.n_switches,
        "yearly_diagnostic": yearly_out,
        "bench_cagr": round(rep.bench_cagr, 4),
        "blackout": "skipped (no PIT-clean historical earnings at scale; disclosed)",
        "vix": "aligned ^INDIAVIX or CALM-fallback (see log)",
        "gate": "MaxDD<0.1635 OR Sharpe>0.698 AND 2022_ret>-0.1025",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join("data", "core_backtest_v3.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
