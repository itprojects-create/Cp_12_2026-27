"""Data health monitor (§§55, 61): freshness + failures, never faked.

Prints one row per known dataset: latest record timestamp, status, age, and
cost/storage economics (§97: bytes from the acquisition ledger; acquisition
costs stay separate from strategy transaction costs and research token costs).

Usage: python scripts/data_health.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.db import sqlite_conn  # noqa: E402

KNOWN = ["NSE/announcements", "BSE/announcements", "NSE/corporate-actions",
         "BSE/corporate-actions", "NSE/equity-eod", "NSE/indices",
         "NSE/bulk-block-deals", "NSE/fii-dii-provisional", "CDSL/fpi-final",
         "NSE/fno-bhavcopy", "NSE/participant-oi", "NSE/participant-volume",
         "NSE/filings"]


def staleness(latest_ts: str, expected: str) -> str:
    if not latest_ts:
        return "no data"
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(latest_ts)).total_seconds() / 3600
    except ValueError:
        return "unknown"
    bounds = {"30min-trading-day": 12, "daily-post-close": 36,
              "daily-post-settlement": 48, "fortnightly-manual": 24 * 20,
              "event-driven-manual": 24 * 90}
    limit = bounds.get(expected, 48)
    if age_h <= limit:
        return "fresh"
    if age_h <= 3 * limit:
        return "STALE"
    return "VERY_STALE"


def main() -> None:
    B.init_tables()
    snap = {(h["source"], h["dataset"]): h for h in B.health_snapshot()}
    print(f"{'Dataset':32s} {'Latest':22s} {'Status':14s} {'Freshness'}")
    print("-" * 92)
    for key in KNOWN:
        src, ds = key.split("/", 1)
        h = snap.get((src, ds))
        if h is None:
            print(f"{key:32s} {'-':22s} {'NOT_COLLECTED':14s} no data")
            continue
        fresh = staleness(h["latest_record_ts"], h["expected_freshness"])
        status = h["status"] if fresh in ("fresh", "no data", "unknown") else "STALE"
        print(f"{key:32s} {h['latest_record_ts'][:19]:22s} {status:14s} {fresh}")
    rows = sqlite_conn().execute(
        "SELECT dataset, COUNT(*), COALESCE(SUM(bytes),0) FROM acquisition_ledger"
        " GROUP BY dataset ORDER BY dataset").fetchall()
    print("\nInfrastructure economics (§97, acquisition-only):")
    total_b = 0
    for ds, n, b in rows:
        total_b += b or 0
        print(f"  {ds:28s} artifacts={n:<6d} bytes={b or 0}")
    print(f"  {'TOTAL':28s} bytes={total_b} (strategy/research costs tracked separately)")


if __name__ == "__main__":
    main()
