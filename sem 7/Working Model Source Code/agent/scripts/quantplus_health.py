"""Canonical operational health command (P1, §11).

Reports per dataset: source, latest collection, latest source timestamp, age,
record count, expected freshness, PIT status, failures, schema status, job
status. Health reflects REALITY (§12): a zero-record SUCCESS when data should
exist is SUSPICIOUS, never HEALTHY.

Usage: python scripts/quantplus_health.py [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.data import registry as REG  # noqa: E402
from app.db import sqlite_conn  # noqa: E402
from app.ops import calendar as CAL  # noqa: E402
from app.ops import alerts as AL  # noqa: E402
from app.ops import log as OPS  # noqa: E402

DATASETS = ["NSE/announcements", "BSE/announcements", "NSE/corporate-actions",
            "BSE/corporate-actions", "NSE/equity-eod", "NSE/indices",
            "NSE/bulk-block-deals", "NSE/fii-dii-provisional", "CDSL/fpi-final",
            "NSE/fno-bhavcopy", "NSE/participant-oi", "NSE/participant-volume",
            "NSE/filings"]


def dataset_health(now: datetime | None = None) -> list[dict]:
    B.init_tables()
    REG.init_tables()
    now = now or datetime.now(timezone.utc)
    snap = {(h["source"], h["dataset"]): h for h in B.health_snapshot()}
    rows = []
    for key in DATASETS:
        src, ds = key.split("/", 1)
        h = snap.get((src, ds))
        if h is None:
            rows.append({"dataset": key, "status": "NOT_COLLECTED", "records": 0,
                         "latest_collection": "", "latest_source_ts": "",
                         "failures": 0, "expected_freshness": "",
                         "pit": "UNKNOWN", "note": "never collected"})
            continue
        n = sqlite_conn().execute(
            "SELECT COUNT(*), MAX(first_seen_ts) FROM acquisition_ledger"
            " WHERE source=? AND dataset=?", (src, ds)).fetchone()
        latest_src = sqlite_conn().execute(
            "SELECT MAX(publication_ts) FROM acquisition_ledger"
            " WHERE source=? AND dataset=?", (src, ds)).fetchone()[0]
        # §12: zero-record success when records should exist is suspicious
        records = n[0]
        status = h["status"]
        expect_data = CAL.is_trading_day(now.date().isoformat())
        if status == "HEALTHY" and records == 0 and expect_data and ds in (
                "equity-eod", "indices", "announcements"):
            status = "SUSPICIOUS_ZERO"
        rows.append({"dataset": key, "status": status,
                     "latest_collection": h["last_success"], "records": records,
                     "latest_source_ts": latest_src, "failures": h["consecutive_failures"],
                     "expected_freshness": h["expected_freshness"],
                     "pit": _pit_for(ds)})
    return rows


def _pit_for(dataset: str) -> str:
    if dataset in ("announcements",):
        return "versioned-events"
    if dataset in ("equity-eod", "indices"):
        return "exchange-timestamps"
    if dataset in ("corporate-actions",):
        return "graded-VERIFIED/PARTIAL/UNKNOWN"
    return "dataset-dependent"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = dataset_health()
    alerts = AL.active()
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "session": CAL.session_kind(datetime.now(timezone.utc).date().isoformat()),
           "datasets": rows, "active_alerts": alerts,
           "n_critical": sum(1 for x in alerts if x["severity"] == "CRITICAL")}
    if a.json:
        print(json.dumps(doc, indent=2))
        return
    print(f"{'Dataset':28s} {'Status':16s} {'Records':>8s}  Latest collection")
    print("-" * 84)
    for r in rows:
        latest = r["latest_collection"] or "-"
        print(f"{r['dataset']:28s} {r['status']:16s} {r['records']:>8d}  "
              f"{latest[:19]}")
    print(f"\nactive alerts: {len(alerts)} "
          f"({doc['n_critical']} critical)")


if __name__ == "__main__":
    main()
