"""Generic backfill engine (§§47–49): checkpointed, resumable, chunked, idempotent.

Usage:
  python scripts/backfill_data.py --dataset equity-eod --start 2024-01-01 --end 2024-03-31 [--chunk week]
  python scripts/backfill_data.py --dataset announcements --symbol INFY.NS --start 2024-01-01 --end 2024-01-31

Chunking: day|week|month (§48). A crash resumes from the checkpoint (§49) —
never restarts. Every window delegates to the dataset's collector; manifests
and content hashes make re-runs idempotent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.data_acquisition import util as U  # noqa: E402

CHUNK_DAYS = {"day": 1, "week": 7, "month": 30}

DATASETS = ("equity-eod", "indices", "bulk-block-deals", "fii-dii-provisional",
            "fno-bhavcopy", "participant-oi", "participant-volume",
            "announcements", "corporate-actions")


def _chunks(start: str, end: str, chunk: str):
    d0 = datetime.fromisoformat(start).date()
    d1 = datetime.fromisoformat(end).date()
    step = CHUNK_DAYS[chunk]
    out, cur = [], d0
    while cur <= d1:
        nxt = min(cur + timedelta(days=step - 1), d1)
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt + timedelta(days=1)
    return out


def _collector(dataset: str):
    from app.data_acquisition.nse import deals as D
    from app.data_acquisition.nse import equity as E
    from app.data_acquisition.nse import fno as F
    from app.data_acquisition.nse import indices as I
    from app.data_acquisition.nse import institutional as N
    from app.data_acquisition.nse import announcements as NA
    from app.data_acquisition.nse import corporate_actions as NCA
    return {"equity-eod": E.NseEquityEod, "indices": I.NseIndices,
            "bulk-block-deals": D.NseDeals, "fii-dii-provisional": N.NseFlows,
            "fno-bhavcopy": F.NseFno, "participant-oi": F.NseParticipantOi,
            "participant-volume": F.NseParticipantVol,
            "announcements": NA.NseAnnouncements,
            "corporate-actions": NCA.NseCorporateActions}[dataset]()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=DATASETS)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--chunk", default="week", choices=tuple(CHUNK_DAYS))
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--resume", action="store_true", default=True)
    a = ap.parse_args()

    col = _collector(a.dataset)
    ckpt = B.checkpoint_get(a.dataset) if a.resume else None
    windows = _chunks(a.start, a.end, a.chunk)
    if ckpt and ckpt["next_window"]:
        windows = [w for w in windows if w[1] >= ckpt["next_window"]]
        print(f"resuming at {ckpt['next_window']} ({len(windows)} windows left)")
    done, failed = [], []
    for ws, we in windows:
        kw: dict = {}
        if a.dataset in ("announcements",) and a.symbol:
            kw = {"symbols": [a.symbol]}
        elif a.dataset in ("corporate-actions",) and a.symbol:
            kw = {"symbols": [a.symbol]}
        elif a.dataset in ("equity-eod", "indices", "bulk-block-deals",
                           "fno-bhavcopy", "participant-oi", "participant-volume"):
            from datetime import date as _d
            days, cur = [], datetime.fromisoformat(ws).date()
            endd = datetime.fromisoformat(we).date()
            while cur <= endd:
                if cur.weekday() < 5:
                    days.append(cur.isoformat())
                cur += timedelta(days=1)
            kw = {"days": days}
        try:
            res = col.fetch(start=ws, end=we, incremental=False, **kw)
            B.checkpoint_set(a.dataset, we, (datetime.fromisoformat(we).date()
                                             + timedelta(days=1)).isoformat())
            done.append({"window": [ws, we], "status": res.status.value,
                         "received": res.records_received})
            if res.status in (B.FetchStatus.SOURCE_UNAVAILABLE,
                              B.FetchStatus.SOURCE_BLOCKED):
                failed.append({"window": [ws, we], "status": res.status.value})
                print(f"STOP: source {res.status.value} at {ws} (resume later)")
                break  # don't hammer a dead/blocked source (§48)
        except Exception as e:  # noqa: BLE001 - checkpoint + continue with next
            B.checkpoint_set(a.dataset, ws, ws, failed=True, failure_note=str(e)[:200])
            failed.append({"window": [ws, we], "status": "ERROR", "note": str(e)[:200]})
    print(json.dumps({"dataset": a.dataset, "windows_done": len(done),
                      "windows_failed": len(failed),
                      "finished_at": datetime.now(timezone.utc).isoformat()}, indent=2))


if __name__ == "__main__":
    main()
