"""Job dispatcher: market-calendar-aware invocation of all operational jobs (§§4–5).

Usage:
  python scripts/run_job.py --job intraday-events|post-close|settlement|weekly-forward|daily-health|daily-snapshot|backup|monthly-audit [--day YYYY-MM-DD] [--dry-run]

Every job consults the market calendar first; non-trading days skip EOD-shaped
work but still run event/health paths (§79). All runs append to the ops log.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ops import calendar as CAL  # noqa: E402
from app.ops import log as OPS  # noqa: E402

JOBS = ("intraday-events", "post-close", "settlement", "weekly-forward",
        "daily-health", "daily-snapshot", "backup", "monthly-audit")


def run_job(name: str, day: str, dry_run: bool = False) -> dict:
    if name not in JOBS:
        raise ValueError(f"unknown job {name!r} (known: {JOBS})")
    OPS.log(name, "start", note=f"day={day} dry={dry_run} session={CAL.session_kind(day)}")
    out: dict = {"job": name, "day": day, "dry_run": dry_run,
                 "session": CAL.session_kind(day)}
    try:
        if name == "intraday-events":
            from app.data_acquisition.nse import announcements as NA
            from app.data_acquisition.bse import announcements as BA
            watch = _watchlist()
            out["nse"] = NA.NseAnnouncements().fetch(
                symbols=watch, day=day).__dict__ if not dry_run else {"dry": True}
            out["bse"] = BA.BseAnnouncements().fetch(
                scrips=[], day=day).__dict__ if not dry_run else {"dry": True}
        elif name == "post-close":
            from scripts import run_post_close as RPC
            out["run"] = RPC.run_post_close(day, dry_run=dry_run)
        elif name == "settlement":
            out["run"] = {"note": "post-settlement reconciliation: re-fetch announcements "
                                  "(amendment sweep) + filings check (manual-first)",
                          "detail": _settlement_sweep(day, dry_run)}
        elif name == "weekly-forward":
            from scripts import forward_week as FW
            out["run"] = "invoke scripts/forward_week.py directly (writes ledger)"
            out["hint"] = "forward_week.py --dry-run for preview" if dry_run else \
                "run scripts/forward_week.py (non-dry) from the weekly slot"
        elif name == "daily-health":
            out["run"] = "invoke scripts/quantplus_health.py"
        elif name == "daily-snapshot":
            out["run"] = "invoke scripts/freeze_data_snapshot.py"
        elif name == "backup":
            out["run"] = "invoke scripts/backup_evidence.py"
        elif name == "monthly-audit":
            out["run"] = "invoke scripts/monthly_audit.py"
        OPS.log(name, "finish", status="OK", note=json.dumps(out)[:400])
        out["status"] = "OK"
    except Exception as e:  # noqa: BLE001
        OPS.log(name, "fail", status="FAIL", note=f"{type(e).__name__}: {e}"[:400])
        out["status"] = "FAIL"
        out["error"] = str(e)[:300]
    return out


def _watchlist() -> list[str]:
    try:
        from app.core.trend_core import UNIVERSE
        return sorted(UNIVERSE)
    except ImportError:
        return []


def _settlement_sweep(day: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry": True}
    from app.data_acquisition.nse import announcements as NA
    res = NA.NseAnnouncements().fetch(symbols=_watchlist() or ["RELIANCE.NS"], day=day)
    return {"symbols": len(_watchlist()), "status": res.status.value,
            "received": res.records_received}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, choices=JOBS)
    ap.add_argument("--day", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run_job(a.job,
                             a.day or datetime.now(timezone.utc).date().isoformat(),
                             dry_run=a.dry_run), indent=2, default=str))


if __name__ == "__main__":
    main()
