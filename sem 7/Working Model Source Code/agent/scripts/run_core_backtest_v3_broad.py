"""Broad-universe v3 backtest: NIFTY500 EQ list (NEW_PLAN next-step 2).

Same frozen v3 rule (app/core/trend_core_v3.py untouched). Tier caps applied:
NIFTY50 names 10%, other NIFTY500 5%. Sector caps from data/nifty500_sectors.json.
Names with <90% index-bar coverage excluded (recent IPOs; disclosed selection
bias — excludes young winners AND losers). Tails padded flat (same as NIFTY50
script). Batch yfinance fetch in chunks. Zero LLM tokens. One read, as-is.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.trend_core import UNIVERSE as NIFTY50, INDEX_TICKER  # noqa: E402
from app.core.trend_core_v3 import run_core_v3  # noqa: E402

START = "2021-01-01"
END = "2026-10-01"
CHUNK = 50


def _closes_single(ticker: str):
    df = yf.download(ticker, start=START, end=END, interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return [float(x) for x in df["Close"].dropna().tolist()]


def _batch(tickers: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        try:
            df = yf.download(chunk, start=START, end=END, interval="1d",
                             auto_adjust=True, progress=False, group_by="ticker")
        except Exception as e:
            print(f"WARN: chunk {i // CHUNK} failed ({e})")
            continue
        if df is None or df.empty:
            print(f"WARN: chunk {i // CHUNK} empty")
            continue
        for t in chunk:
            try:
                closes = df[t]["Close"].dropna()
                vals = [float(x) for x in closes.tolist()]
                if vals:
                    out[t] = vals
            except Exception:
                continue
    return out


def main() -> None:
    with open("data/nifty500.txt", encoding="utf-8-sig") as f:
        n500 = [l.strip().upper() for l in f if l.strip()]
    with open("data/nifty500_sectors.json", encoding="utf-8-sig") as f:
        sectors = json.load(f)
    idx = _closes_single(INDEX_TICKER)
    n = len(idx)
    print(f"index bars: {n}")
    got = _batch(sorted(set(n500)))
    print(f"fetched: {len(got)}/{len(n500)}")
    names, excluded = {}, []
    for t, cs in got.items():
        if len(cs) < n * 0.9:
            excluded.append(t)
            continue
        names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
    # Always-known exclusions (fetch-level): disclosed, not silent
    for t in n500:
        if t not in got and t not in excluded:
            excluded.append(t)
    tier = {t: ("nifty50" if t in NIFTY50 else "nifty500") for t in names}
    sector = {t: sectors.get(t, "UNKNOWN") for t in names}
    print(f"kept: {len(names)}, excluded: {len(excluded)}")
    try:
        vix = _closes_single("^INDIAVIX")
        vix = (vix + [vix[-1]] * n)[:n] if len(vix) != n else vix
    except Exception as e:
        print(f"WARN: VIX failed ({e}); CALM fallback")
        vix = None
    rep = run_core_v3(idx, names, vix_closes=vix, tier=tier, sector=sector)
    out = {
        "frozen_rule": "app/core/trend_core_v3.py (prereg data/prereg_core_v3.md)",
        "universe": "NIFTY500 EQ (>=90% coverage)",
        "n_days": rep.n_days, "n_names": rep.n_names,
        "n_excluded": len(excluded), "excluded_sample": sorted(excluded)[:30],
        "total_return": round(rep.total_return, 4), "cagr": round(rep.cagr, 4),
        "ann_vol": round(rep.ann_vol, 4), "sharpe": round(rep.sharpe, 3),
        "max_drawdown": round(rep.max_drawdown, 4),
        "total_cost": round(rep.total_cost, 5),
        "avg_exposure": round(rep.exposure, 4), "n_switches": rep.n_switches,
        "bench_cagr": round(rep.bench_cagr, 4),
        "selection_bias": "excluded <90%-coverage names (young IPOs); survivorship bias remains (2026 list)",
        "tier_caps": "nifty50 10% / nifty500 5% (+ sector 25%)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join("data", "core_backtest_v3_broad.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
