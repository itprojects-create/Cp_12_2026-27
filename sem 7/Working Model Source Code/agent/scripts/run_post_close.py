"""Post-close orchestrator (§8): ordered daily collection after publication.

Sequence: calendar validation -> EOD -> delivery(implicit in full bhav when
enabled) -> indices/VIX/TRI -> bulk/block -> FII/DII -> F&O -> participant
OI/volume -> corporate actions -> late announcements -> quality checks ->
registry update -> snapshot. Feeds have different publication times: each step
is independent (one failure never aborts the rest), and non-trading days skip
EOD expectations (§79).

Usage: python scripts/run_post_close.py [--day YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.data_acquisition.nse import announcements as NA  # noqa: E402
from app.data_acquisition.nse import corporate_actions as NCA  # noqa: E402
from app.data_acquisition.nse import deals as D  # noqa: E402
from app.data_acquisition.nse import equity as E  # noqa: E402
from app.data_acquisition.nse import fno as F  # noqa: E402
from app.data_acquisition.nse import indices as I  # noqa: E402
from app.data_acquisition.nse import institutional as N  # noqa: E402
from app.data import registry as REG  # noqa: E402
from app.ops import calendar as CAL  # noqa: E402
from app.ops import log as OPS  # noqa: E402


def run_post_close(day: str, dry_run: bool = False, symbols: list[str] | None = None,
                   full_bhav: bool = True) -> dict:
    """Execute the ordered sequence. Returns the run record (steps + snapshot)."""
    OPS.log("post-close", "start", note=f"day={day} dry={dry_run}")
    kind = CAL.session_kind(day)
    steps: dict = {"day": day, "session": kind, "steps": {}, "dry_run": dry_run}
    if kind in ("WEEKEND", "HOLIDAY"):
        steps["note"] = f"{kind}: no EOD expected (§79); announcements only"
    trading = CAL.is_trading_day(day)

    def _step(name: str, fn):
        if dry_run:
            steps["steps"][name] = {"status": "DRY_RUN", "received": 0}
            return
        try:
            r = fn()
            steps["steps"][name] = {"status": r.status.value,
                                    "received": r.records_received,
                                    "written": r.records_written}
        except Exception as e:  # noqa: BLE001 - per-step isolation
            steps["steps"][name] = {"status": "ERROR", "note": f"{type(e).__name__}: {e}"[:200]}
            B.log_error("post-close", name, day, "ERROR", str(e)[:200])

    if trading:
        _step("equity-eod", lambda: E.NseEquityEod().fetch(days=[day], full_bhav=full_bhav))
        _step("indices", lambda: I.NseIndices().fetch(days=[day]))
    else:
        steps["steps"]["equity-eod"] = {"status": "SKIPPED", "note": "no session"}
        steps["steps"]["indices"] = {"status": "SKIPPED", "note": "no session"}
    _step("bulk-block", lambda: D.NseDeals().fetch(days=[day] if trading else []))
    _step("fii-dii", lambda: N.NseFlows().fetch(day=day))
    if trading:
        _step("fno", lambda: F.NseFno().fetch(days=[day]))
        _step("participant-oi", lambda: F.NseParticipantOi().fetch(days=[day]))
        _step("participant-vol", lambda: F.NseParticipantVol().fetch(days=[day]))
    _step("corp-actions", lambda: NCA.NseCorporateActions().fetch(
        symbols=symbols or [], day=day))
    _step("announcements", lambda: NA.NseAnnouncements().fetch(
        symbols=symbols or [], day=day))

    # quality + registry + snapshot (skipped inputs stay missing, never faked)
    snap_id = ""
    if not dry_run:
        REG.seed_known()
        for name in ("equity-eod", "indices", "bulk-block-deals", "fii-dii-provisional",
                     "fno-bhavcopy", "participant-oi", "participant-volume",
                     "nse-announcements", "nse-corporate-actions"):
            REG.record_usage(name, f"post-close-{day}", "daily-collection")
        snap_id = f"SNAP-{day.replace('-', '')}"
        try:
            import subprocess
            subprocess.run(["python", "scripts/freeze_data_snapshot.py", "--id", snap_id],
                           capture_output=True, text=True, cwd=".", timeout=120)
        except Exception as e:  # noqa: BLE001 - snapshot failure must not void collection
            steps["snapshot_error"] = f"{type(e).__name__}: {e}"[:200]
    steps["snapshot_id"] = snap_id
    worst = max((s.get("status", "") for s in steps["steps"].values()), default="OK")
    OPS.log("post-close", "finish", status="OK" if worst not in ("ERROR",) else "PARTIAL",
            snapshot_id=snap_id, note=json.dumps(
                {k: v.get("status") for k, v in steps["steps"].items()})[:500])
    return steps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbols", nargs="*", default=[])
    a = ap.parse_args()
    day = a.day or datetime.now(timezone.utc).date().isoformat()
    print(json.dumps(run_post_close(day, dry_run=a.dry_run, symbols=a.symbols), indent=2))


if __name__ == "__main__":
    main()
