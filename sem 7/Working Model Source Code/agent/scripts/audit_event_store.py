"""Audit the event store: counts, hashes, duplicates, amendments, failures (§77).

Read-only. Verifies append-only integrity (raw payload rehash matches),
duplicate/amendment linkage, and prints the §70-style source coverage stub
(uptime inputs land once the live feed runs on schedule).

Usage: python scripts/audit_event_store.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import sqlite_conn  # noqa: E402
from app.events import store as ST  # noqa: E402


def main() -> None:
    ST.init_tables()
    stats = ST.store_stats()
    # integrity: rehash every raw payload, compare to stored hash
    rows = sqlite_conn().execute(
        "SELECT record_id, exchange, symbol, title, body, publication_ts, payload_hash"
        " FROM raw_events").fetchall()
    mismatched = []
    for r in rows:
        expect = ST.payload_hash(r[1], r[2], r[3], r[4], r[5])
        if expect != r[6]:
            mismatched.append(r[0])
    links = sqlite_conn().execute(
        "SELECT relation, COUNT(*) FROM event_links GROUP BY relation").fetchall()
    failures = sqlite_conn().execute(
        "SELECT kind, COUNT(*) FROM source_failures GROUP BY kind").fetchall()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store": stats,
        "raw_rows_checked": len(rows),
        "hash_mismatches": mismatched,
        "links_by_relation": {k: v for k, v in links},
        "failures_by_kind": {k: v for k, v in failures},
        "coverage_note": ("live-feed uptime inputs pending scheduled runs; "
                          "local-feed batches audited via manifests"),
    }
    print(json.dumps(report, indent=2))
    if mismatched:
        print("HASH MISMATCH — FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
