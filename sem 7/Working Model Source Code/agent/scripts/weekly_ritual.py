"""Weekly autonomous ritual (§§59–62): ordered operations, fail-closed.

Order: 1 source health → 2 snapshot validation → 3 settle matured labels →
4 experiment evidence → 5 judge founders/challengers → 6 calibration outcomes →
7 memory maintenance → 8 foundry-if-allowed → 9 failure-first weekly report
(.json + .md) → 10 freeze artifact → 11 backup.

Any step may yield NO_JUDGMENT (missing/stale/corrupt/PIT_UNKNOWN/invalid);
the ritual records and continues — it never manufactures data or loosens gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "scripts")

from app.ops import log as OPS  # noqa: E402


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def settle_calibration_outcomes() -> dict:
    """Bridge matured research-experiment terminal states into calibration
    outcomes (§65 settles stored priors; never computes prematurely — the
    report stays INSUFFICIENT until n>=30 regardless)."""
    from app.db import sqlite_conn
    from app.research import calibration as CAL
    CAL.init_tables()
    from app.research_memory import store as ST
    ST.init_tables()
    exps = sqlite_conn().execute(
        "SELECT hypothesis_fp, status FROM research_experiments").fetchall()
    settled = 0
    for hfp, status in exps:
        if status in ("EXPERIMENTING", "PROPOSED", "DUPLICATE"):
            continue  # not mature — never settle early
        CAL.settle_prediction(hfp, status)
        settled += 1
    return {"settled": settled, "calibration": CAL.calibration_report()}


def memory_maintenance() -> dict:
    """Read-only maintenance report (no deletion policy exists — nothing is
    purged; duplicates/corpses counted for the weekly report)."""
    from app.db import sqlite_conn
    from app.research_memory import store as ST
    ST.init_tables()
    hyps = ST.list_hypotheses()
    n_exp = sqlite_conn().execute("SELECT COUNT(*) FROM research_experiments").fetchone()
    n_exp = n_exp[0] if n_exp else 0
    return {"hypotheses": len(hyps),
            "duplicates": sum(1 for h in hyps if h["status"] == "DUPLICATE"),
            "corpses": len(ST.list_corpses()),
            "experiments": n_exp}


def run_weekly(day: str | None = None, dry_run: bool = False,
               freeze_path: str | None = None) -> dict:
    """Execute the 11-step order. Returns the weekly record."""
    from scripts import forward_week as FW
    day = day or datetime.now(timezone.utc).date().isoformat()
    OPS.log("weekly", "start", note=f"day={day} dry={dry_run}")
    rec: dict = {"day": day, "as_of": _utcnow(), "dry_run": dry_run, "steps": {}}
    order: list[str] = []

    import scripts.quantplus_health as QH
    health = QH.dataset_health()
    rec["steps"]["1_health"] = {"datasets": len(health),
                                "not_collected": sum(1 for r in health
                                                     if r["status"] == "NOT_COLLECTED")}
    order.append("1_health")

    from app.data_acquisition import snapshots as SNAP
    snaps = sorted([f for f in os.listdir("data/snapshots") if f.endswith(".json")]) \
        if os.path.isdir("data/snapshots") else []
    validations = [SNAP.validate_snapshot(s[:-5]) for s in snaps[-2:]]
    rec["steps"]["2_snapshots"] = {"checked": len(validations),
                                   "invalid": sum(1 for v in validations
                                                  if not v["valid"])}
    order.append("2_snapshots")

    from app.forward import settle as SETTLE
    try:
        settling = SETTLE.settle_as_of(day + "T23:59:59+00:00", horizon_days=5)
    except Exception as e:  # noqa: BLE001
        settling = {"error": f"{type(e).__name__}: {e}"[:200]}
    rec["steps"]["3_settle"] = settling
    order.append("3_settle")

    from app.forward import settle as SETTLE2
    rec["steps"]["4_experiment_evidence"] = SETTLE2.experiment_counts(
        "2026-10-10T00:00:00+00:00", day + "T23:59:59+00:00")
    order.append("4_experiment_evidence")

    week = FW.run_week(dry_run=dry_run, freeze_path=freeze_path)
    rec["steps"]["5_judge"] = {"verdict": week.get("verdict", "judged"),
                               "window": week.get("window_no"),
                               "artifact": week.get("artifact_path", "")}
    order.append("5_judge")

    rec["steps"]["6_calibration"] = settle_calibration_outcomes()
    order.append("6_calibration")
    rec["steps"]["7_memory"] = memory_maintenance()
    order.append("7_memory")

    from app.config import settings
    from app.forward import settle as SETTLE3
    fwd_rows = SETTLE3.experiment_counts(
        "2026-10-10T00:00:00+00:00", day + "T23:59:59+00:00")["announcements_received"]
    allowed = settings.RESEARCH_FOUNDRY_ENABLED and fwd_rows > 0 and not dry_run
    rec["steps"]["8_foundry"] = {"allowed": allowed,
                                 "reason": "no forward rows yet" if fwd_rows == 0
                                 else ("dry-run" if dry_run else "rows available")}
    order.append("8_foundry")

    md = render_weekly_md(rec, week)
    order.append("9_report")
    artifact = week.get("artifact_path", "")
    digest = ""
    if artifact and os.path.exists(artifact):
        h = hashlib.sha256()
        with open(artifact, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()[:16]
    md_path = ""
    if not dry_run:
        md_path = os.path.join("data", f"forward_week_report_{day}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
    rec["steps"]["9_report"] = {"md": md_path}
    rec["steps"]["10_freeze"] = {"artifact": artifact, "sha16": digest}
    order.append("10_freeze")

    if not dry_run:
        try:
            import scripts.backup_evidence as BE
            rec["steps"]["11_backup"] = {
                "backup": BE.run_backup(os.path.join("data", "backups"))["backup"]}
        except Exception as e:  # noqa: BLE001
            rec["steps"]["11_backup"] = {"error": f"{type(e).__name__}: {e}"[:200]}
    else:
        rec["steps"]["11_backup"] = {"skipped": "dry-run"}
    order.append("11_backup")

    rec["order"] = order
    OPS.log("weekly", "finish", status="OK", note=json.dumps(
        {"verdict": rec["steps"]["5_judge"].get("verdict")})[:300])
    return rec


def render_weekly_md(rec: dict, week: dict) -> str:
    j = rec["steps"]["5_judge"]
    lines = [f"# Forward week — {rec['day']}", "",
             f"verdict: {j.get('verdict', 'judged')}  window: {j.get('window')}",
             f"as_of: {rec['as_of']}", "",
             "## Health / gaps",
             json.dumps({k: v for k, v in rec["steps"]["1_health"].items()}, indent=1), "",
             "## Settlement / calibration",
             json.dumps({**rec["steps"]["3_settle"],
                         "calibration": rec["steps"]["6_calibration"].get(
                             "calibration", {}).get("status")}, indent=1, default=str), "",
             "## Founders / deaths / promotions",
             json.dumps({"judged": len(week.get("judged", [])),
                         "allocation": week.get("allocation", {})}, indent=1, default=str), "",
             "## Spend / incidents",
             json.dumps(rec["steps"].get("4_experiment_evidence", {}), indent=1)[:800], "",
             "_Failure-first: weaknesses precede claims; no threshold advice in this report._"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--freeze", default=None)
    a = ap.parse_args()
    print(json.dumps(run_weekly(a.day, dry_run=a.dry_run, freeze_path=a.freeze),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
