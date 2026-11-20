"""Ingest announcements into the immutable store (§77).

Sources (in order): local JSONL feed files (deterministic, auditable) and/or
best-effort live NSE fetch per watchlist symbol. Every run emits a §17 batch
manifest; source failures are logged explicitly (§18), never as empty success.

Usage:
  python scripts/ingest_announcements.py --feed data/announcements/*.jsonl
  python scripts/ingest_announcements.py --live RELIANCE.NS INFY.NS
  python scripts/ingest_announcements.py --feed 'data/announcements/*.jsonl' --live RELIANCE.NS
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.events import ingest as ING  # noqa: E402
from app.events import store as ST  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=None, help="glob for local JSONL feed files")
    ap.add_argument("--live", nargs="*", default=[], help="symbols for best-effort NSE fetch")
    ap.add_argument("--source-version", default="cli-v1")
    a = ap.parse_args()

    raws: list[dict] = []
    if a.feed:
        raws.extend(ING.read_local_feed(a.feed))
        print(f"feed rows: {len(raws)}")
    failures = 0
    for sym in a.live:
        rows = ING.fetch_nse_announcements(sym)
        if not rows:
            ST.log_source_failure("NSE", "SOURCE_UNAVAILABLE",
                                  f"live fetch returned nothing for {sym}")
            failures += 1
        raws.extend(rows)
    if not raws:
        ST.log_source_failure("CLI", "SOURCE_UNAVAILABLE", "no rows from any source")
        print(json.dumps({"batches": [], "failures_logged": failures + 1}))
        return
    manifest = ST.ingest_batch("CLI", raws, source_version=a.source_version)
    print(json.dumps({"manifest": manifest, "store": ST.store_stats()}, indent=2))


if __name__ == "__main__":
    main()
