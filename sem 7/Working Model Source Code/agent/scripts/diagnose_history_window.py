"""Part A step 1: which branch did each cached session hit — real distribution or fallback?

Reads stored exhaustion checkpoints from recent eval runs and, for each session,
re-derives what exhaustion_features() saw: the Technical pull is lookback=60,
so hist = bars strictly before asof within that <=60-bar frame.
Prints stored threshold + recomputed branch + available history depths.
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app.data.yfinance_provider import YFinanceProvider
from app.db import sqlite_conn

REPORTS = ["data/eval_report_20260919T160958Z.json",   # v5 new-24
           "data/eval_report_20260920T074259Z.json",   # v5.1 orig-24
           "data/eval_report_20260920T092702Z.json",   # v5.1 new-24
           "data/eval_report_20260920T113129Z.json",   # M3 new-24
           "data/eval_report_20260920T164633Z.json"]   # M3 orig-24


def main() -> None:
    conn = sqlite_conn()
    n_fb = n_real = n_missing = 0
    shown = 0
    for path in REPORTS:
        if not os.path.exists(path):
            print(f"  skip missing {path}")
            continue
        rep = json.load(open(path))
        for r in rep["results"]:
            sid = r["session"]
            ex = conn.execute("SELECT payload FROM checkpoints WHERE session_id=? AND stage=?",
                              (sid, "exhaustion")).fetchone()
            if not ex:
                n_missing += 1
                continue
            e = json.loads(ex[0])
            thr = float(e["exhaustion_threshold_pct"])
            # What the Technical pull actually gave exhaustion_features():
            as_of = datetime.fromisoformat(r["as_of"]).replace(tzinfo=timezone.utc)
            try:
                df60 = YFinanceProvider().ohlcv(r["instrument"], as_of, "1d", lookback=60)
                df400 = YFinanceProvider().ohlcv(r["instrument"], as_of, "1d", lookback=400)
            except Exception as ex2:
                print(f"  refetch failed {r['instrument']} {r['as_of']}: {type(ex2).__name__}")
                continue
            n60, n400 = len(df60), len(df400)
            # hist len inside the 60-bar frame at asof_idx=len-1
            hist_in_frame = n60 - 1
            branch = "REAL" if hist_in_frame >= 60 else "FALLBACK"
            if branch == "REAL":
                n_real += 1
            else:
                n_fb += 1
            if shown < 6 and branch == "FALLBACK":
                shown += 1
                print(f"  e.g. {r['instrument']:14s} {r['as_of']}: stored_thr={thr} "
                      f"df60_len={n60} ({df60.index[0].date()}..{df60.index[-1].date()}) "
                      f"hist_in_frame={hist_in_frame} -> {branch}; "
                      f"df400_len={n400} (hist_if_deep={n400 - 1})")
    print(f"\nFALLBACK={n_fb} REAL={n_real} MISSING_CKPT={n_missing}")


if __name__ == "__main__":
    main()
