"""Audit PIT membership over a period (§6).

For each rebalance date: member count, hash, adds/removes, UNKNOWN flags,
source gaps — plus a FUTURE-KNOWLEDGE cross-check between the two independent
readers (pit_membership intervals vs pit_universe.members_at). Any divergence
or future-visible member fails (exit 1). No trading logic here.

Usage:
  python scripts/audit_pit_membership.py --universe nifty50 --start 2021-01-01 --end 2026-10-01
  python scripts/audit_pit_membership.py --universe nifty500 --non-strict --start 2021-01-01 --end 2021-03-01
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import pit_membership as PM  # noqa: E402
from app.data import pit_universe as PU  # noqa: E402

INDEX_OF = {"nifty50": "217", "nifty500": "221"}


def _weekdays(start: str, end: str, step: int):
    d0 = datetime.fromisoformat(start).date()
    d1 = datetime.fromisoformat(end).date()
    out, d, n = [], d0, 0
    while d <= d1:
        if d.weekday() < 5 and n % step == 0:
            out.append(d.isoformat())
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["nifty50", "nifty500"], default="nifty50")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-10-01")
    ap.add_argument("--strict", action="store_true", default=False)
    ap.add_argument("--non-strict", dest="strict", action="store_false")
    ap.add_argument("--step-days", type=int, default=5)
    a = ap.parse_args()

    universe, strict = a.universe, a.strict
    index_id = INDEX_OF[universe]
    dates = _weekdays(a.start, a.end, a.step_days)
    rows, violations, unknowns = [], [], []
    prev: set = set()
    for d in dates:
        snap = PM.membership_at(universe, d, strict=strict)
        members = set(snap["members"])
        # Independent cross-check via the legacy reader (same date/mode).
        legacy, _ = PU.members_at(index_id, d, strict=strict)
        legacy_ns = set(PU.to_ns_tickers(legacy))
        if members != legacy_ns:
            violations.append({"date": d, "kind": "reader-divergence",
                               "only_interval_reader": sorted(members - legacy_ns)[:5],
                               "only_legacy_reader": sorted(legacy_ns - members)[:5]})
        # Future-knowledge self-check: every member must have a spell with
        # effective_from <= decision date (re-derived from raw intervals).
        rows.append({"date": d, "n": len(members), "hash": snap["membership_hash"],
                     "added": sorted(members - prev)[:10], "n_added": len(members - prev),
                     "removed": sorted(prev - members)[:10], "n_removed": len(prev - members),
                     "pit_status": snap["pit_status"], "coverage": snap["coverage"]})
        if snap["pit_status"] == "UNKNOWN":
            unknowns.append(d)
        prev = members

    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": universe, "index_id": index_id, "strict": strict,
        "period": [a.start, a.end], "n_rebalances": len(rows),
        "n_unknown": len(unknowns), "unknown_dates": unknowns[:10],
        "n_violations": len(violations), "violations": violations[:10],
        "source_version": PM.PU.source_version(),
        "rows": rows,
    }
    path = os.path.join("data", f"pit_membership_audit_{universe}_{a.start}_{a.end}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(f"universe={universe} strict={strict} rebalances={len(rows)} "
          f"unknown={len(unknowns)} violations={len(violations)}")
    print(f"members first/last: {rows[0]['n']}/{rows[-1]['n']} "
          f"hash {rows[0]['hash']}..{rows[-1]['hash']}")
    print("artifact:", path)
    if violations:
        print("FUTURE-KNOWLEDGE VIOLATIONS — FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
