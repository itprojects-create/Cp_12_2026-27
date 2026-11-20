"""One-shot v4 backtests (prereg data/prereg_core_v4.md, no sequential tuning).

--universe nifty50: 37-name frozen list (comparability vs v3).
--universe broad:   NIFTY500 EQ >=90% coverage + tier/sector caps (dust-fix check).
--universe pit50|pit500: PIT start-date membership (prereg_pit_universe.md,
  Amendment 1: strict=False with disclosed weak counts). Diagnostic reruns for
  bias measurement, NOT new claims.
Zero LLM tokens. Each universe: one read, recorded as-is.
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
from app.core.trend_core_v4 import run_core_v4  # noqa: E402

START = "2021-01-01"
END = "2026-10-01"
CHUNK = 50

# Blind-test override (prereg_blind_2015_2020.md): set ONLY via --start/--end.
# Defaults preserve the original window exactly.
_START = START
_END = END


def _single(ticker: str):
    df = yf.download(ticker, start=_START, end=_END, interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    closes = [float(x) for x in df["Close"].dropna().tolist()]
    dates = [str(d.date()) for d in df["Close"].dropna().index]
    return closes, dates


def _batch(tickers: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        try:
            df = yf.download(chunk, start=_START, end=_END, interval="1d",
                             auto_adjust=True, progress=False, group_by="ticker")
        except Exception as e:
            print(f"WARN: chunk {i // CHUNK} failed ({e})")
            continue
        if df is None or df.empty:
            print(f"WARN: chunk {i // CHUNK} empty")
            continue
        for t in chunk:
            try:
                vals = [float(x) for x in df[t]["Close"].dropna().tolist()]
                if vals:
                    out[t] = vals
            except Exception:
                continue
    return out


def main(which: str) -> None:
    idx, dates = _single(INDEX_TICKER)
    n = len(idx)
    try:
        vix = _single("^INDIAVIX")[0]
        vix = (vix + [vix[-1]] * n)[:n] if len(vix) != n else vix
    except Exception as e:
        print(f"WARN: VIX failed ({e}); CALM fallback")
        vix = None
    tier, sector, excluded = {}, {}, []
    universe_meta: dict = {}
    if which in ("pit50", "pit500"):
        from app.data.pit_universe import start_date_universe
        index_id = "217" if which == "pit50" else "221"
        want, universe_meta = start_date_universe(index_id, _START, strict=False)
        print(f"PIT universe {index_id} @ {_START}: {len(want)} names "
              f"(weak rows: {universe_meta['weak_rows_included']})")
        pit50, _ = start_date_universe("217", _START, strict=False)
        pit50set = set(pit50)
        if which == "pit500":
            with open("data/nifty500_sectors.json", encoding="utf-8-sig") as f:
                secmap = json.load(f)
        else:
            secmap = {}
        got = _batch(sorted(set(want)))
        names = {}
        for t, cs in got.items():
            if len(cs) < n * 0.9 or not cs:
                excluded.append(t)
                continue
            names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
        for t in want:
            if t not in got and t not in excluded:
                excluded.append(t)
        tier = {t: ("nifty50" if t in pit50set else "nifty500") for t in names}
        # No UNKNOWN bucket: names absent from secmap get NO sector entry, so the
        # 25% cap only binds real sectors. (An all-UNKNOWN map would cap the whole
        # book at 25% and starve every name below the turnover dust filter —
        # that exact bug voided the first pit50 run; see notes in its JSON.)
        sector = {t: secmap[t] for t in names if t in secmap}
    elif which == "broad":
        with open("data/nifty500.txt", encoding="utf-8-sig") as f:
            want = [l.strip().upper() for l in f if l.strip()]
        with open("data/nifty500_sectors.json", encoding="utf-8-sig") as f:
            secmap = json.load(f)
        got = _batch(sorted(set(want)))
        names = {}
        for t, cs in got.items():
            if len(cs) < n * 0.9 or not cs:
                excluded.append(t)
                continue
            names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
        for t in want:
            if t not in got and t not in excluded:
                excluded.append(t)
        tier = {t: ("nifty50" if t in NIFTY50 else "nifty500") for t in names}
        sector = {t: secmap.get(t, "UNKNOWN") for t in names}
    else:
        names = {}
        for t in NIFTY50:
            try:
                cs, _ = _single(t)
            except Exception as e:
                print(f"WARN: {t} ({e}); excluded")
                excluded.append(t)
                continue
            if not cs:
                excluded.append(t)
                continue
            names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
    print(f"index bars: {n}, names: {len(names)}, excluded: {len(excluded)}, vix: {'ok' if vix else 'CALM'}")
    rep = run_core_v4(idx, names, vix_closes=vix, tier=tier, sector=sector)
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
    out = {
        "frozen_rule": "app/core/trend_core_v4.py (prereg data/prereg_core_v4.md, one run)",
        "universe": which, "n_days": rep.n_days, "n_names": rep.n_names,
        "universe_meta": universe_meta,
        "n_excluded": len(excluded), "excluded_sample": sorted(excluded)[:30],
        "total_return": round(rep.total_return, 4), "cagr": round(rep.cagr, 4),
        "ann_vol": round(rep.ann_vol, 4), "sharpe": round(rep.sharpe, 3),
        "max_drawdown": round(rep.max_drawdown, 4),
        "total_cost": round(rep.total_cost, 5),
        "avg_exposure": round(rep.exposure, 4), "n_switches": rep.n_switches,
        "yearly": {yr: {"ret": round(v["end_eq"] / v["start_eq"] - 1, 4),
                        "intra_yr_dd": round(v["trough"] / v["peak"] - 1, 4)} for yr, v in yearly.items()},
        "bench_cagr_corrected": round(rep.bench_cagr, 4),
        "bench_note": "corrected math (mean of total returns); v2/v3 bench numbers keep old formula",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    tag = f"{which}_{_START}_{_END}" if (_START, _END) != (START, END) else which
    path = os.path.join("data", f"core_backtest_v4_{tag}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("report:", path)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["nifty50", "broad", "pit50", "pit500"],
                      default="nifty50")
    ap.add_argument("--start", default=START, help="blind-test override (prereg only)")
    ap.add_argument("--end", default=END, help="blind-test override (prereg only)")
    a = ap.parse_args()
    _START, _END = a.start, a.end  # module scope here: plain assignment is global
    main(a.universe)
