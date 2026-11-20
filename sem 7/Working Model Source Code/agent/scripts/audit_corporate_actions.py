"""Corporate-action PIT coverage audit (P4, §§30–35).

Quantifies the acquisition corp-action store: by type, by year, by universe,
VERIFIED/PARTIAL/UNKNOWN grades, filing linkage, identity/timestamp coverage.
Audit only — never fills UNKNOWNs (§35).

Usage: python scripts/audit_corporate_actions.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import actions_store as STORE  # noqa: E402
from app.db import sqlite_conn  # noqa: E402

VERIFIED_MEANING = ("official action + original official disclosure + knowability timestamp")
PARTIAL_MEANING = ("official action + effective/ex-date + incomplete original timestamp")
UNKNOWN_MEANING = ("cannot establish safe historical availability")


def main() -> None:
    STORE.init_tables()
    rows = sqlite_conn().execute(
        "SELECT exchange, symbol, action_type, ex_date, filing_record_id,"
        " announcement_ts, pit_confidence FROM corp_actions").fetchall()
    by_type: dict[str, Counter] = {}
    by_year: dict[str, Counter] = {}
    by_universe: dict[str, Counter] = {}
    missing_identity = missing_ts = linked = 0
    try:
        from app.core.trend_core import UNIVERSE as N50
    except ImportError:
        N50 = set()
    for exch, sym, kind, exd, filing, ann, conf in rows:
        by_type.setdefault(kind, Counter())[conf or "UNKNOWN"] += 1
        by_year.setdefault((exd or "?")[:4], Counter())[conf or "UNKNOWN"] += 1
        uni = "NIFTY50" if sym in N50 else "OTHER"
        by_universe.setdefault(uni, Counter())[conf or "UNKNOWN"] += 1
        if not sym or len(sym) < 5:
            missing_identity += 1
        if not exd or len(exd) != 10:
            missing_ts += 1
        if filing:
            linked += 1
    n = len(rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": n,
        "verification_levels": {"VERIFIED": VERIFIED_MEANING, "PARTIAL": PARTIAL_MEANING,
                                "UNKNOWN": UNKNOWN_MEANING},
        "by_type": {k: dict(v) for k, v in by_type.items()},
        "by_year": {k: dict(v) for k, v in by_year.items()},
        "by_universe": {k: dict(v) for k, v in by_universe.items()},
        "linked_announcement_pct": round(100 * linked / n, 2) if n else 0.0,
        "unlinked_pct": round(100 * (n - linked) / n, 2) if n else 0.0,
        "missing_identity": missing_identity, "missing_timestamp": missing_ts,
        "note": ("UNKNOWNs preserved, never auto-filled (§35). Production store is "
                 "empty until live collection: coverage below describes fixtures only.")
        if n == 0 else "coverage as stored",
    }
    path = os.path.join("data", "corp_action_coverage_20261010.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "by_year"}, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
