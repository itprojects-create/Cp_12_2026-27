"""Part 0 (informational): would loosened exhaustion thresholds have fired?

For each of the 48 real v5/v5.1 sessions, takes the stored ret_5d_pct and places
it against that ticker's OWN historical |ret_5d| distribution (same construction
as exhaustion_features(): strictly pre-asof bars). Reports whether the session
would have fired at the 90th (live), 80th, and 75th percentile thresholds.
Report-only: changes nothing.
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
import pandas as pd
from app.data.yfinance_provider import YFinanceProvider
from app.db import sqlite_conn

REPORTS = ["data/eval_report_20260920T074259Z.json",   # v5.1 original-24
           "data/eval_report_20260920T092702Z.json"]   # v5.1 new-24


def hist_dist(instrument: str, as_of):
    """|ret_5d| distribution strictly before as_of (mirrors exhaustion_features)."""
    df = YFinanceProvider().ohlcv(instrument, as_of, "1d", lookback=400)
    closes = df["Close"].dropna()
    # bars strictly before the last (asof) bar
    hist = closes.iloc[:-1]
    if len(hist) < 60:
        return None, len(hist)
    r5 = hist.pct_change(5).abs().dropna() * 100
    return r5, len(hist)


def pct_rank(dist: pd.Series, value: float) -> float:
    return float((dist <= abs(value)).mean() * 100)


def main() -> None:
    conn = sqlite_conn()
    rows = []
    for path in REPORTS:
        rep = json.load(open(path))
        for r in rep["results"]:
            sid = r["session"]
            ex = conn.execute("SELECT payload FROM checkpoints WHERE session_id=? AND stage=?",
                              (sid, "exhaustion")).fetchone()
            if not ex:
                print(f"  no exhaustion ckpt for {r['instrument']} {r['as_of']}")
                continue
            e = json.loads(ex[0])
            ret5 = float(e["ret_5d_pct"])
            as_of = datetime.fromisoformat(r["as_of"]).replace(tzinfo=timezone.utc)
            try:
                dist, n = hist_dist(r["instrument"], as_of)
            except Exception as ex2:
                print(f"  hist unavailable {r['instrument']} {r['as_of']}: {type(ex2).__name__}")
                continue
            if dist is None:
                print(f"  short history ({n} bars): {r['instrument']} {r['as_of']} ret5d={ret5:+.2f}")
                continue
            t90 = max(float(dist.quantile(0.90)), 1.0)
            t80 = max(float(dist.quantile(0.80)), 1.0)
            t75 = max(float(dist.quantile(0.75)), 1.0)
            rows.append({"instrument": r["instrument"], "as_of": r["as_of"], "ret5d": ret5,
                         "n_hist": n, "pct": pct_rank(dist, ret5),
                         "f90": abs(ret5) >= t90, "f80": abs(ret5) >= t80, "f75": abs(ret5) >= t75,
                         "t90": round(t90, 2), "t80": round(t80, 2), "t75": round(t75, 2)})
    print(f"{'instrument':14s} {'as_of':10s} {'ret5d':>7s} {'pct':>6s} "
          f"{'90th':>5s} {'80th':>5s} {'75th':>5s}  (thr90/thr80/thr75)")
    for x in rows:
        print(f"{x['instrument']:14s} {x['as_of']:10s} {x['ret5d']:+7.2f} {x['pct']:6.1f} "
              f"{str(x['f90']):>5s} {str(x['f80']):>5s} {str(x['f75']):>5s}  "
              f"({x['t90']}/{x['t80']}/{x['t75']})")
    n = len(rows)
    print(f"\nn={n} sessions with history; fire@90th={sum(x['f90'] for x in rows)} "
          f"fire@80th={sum(x['f80'] for x in rows)} fire@75th={sum(x['f75'] for x in rows)}")


if __name__ == "__main__":
    main()
