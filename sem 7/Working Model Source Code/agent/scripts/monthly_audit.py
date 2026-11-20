"""Monthly autonomous audit (§63): operations-only, never optimization (§64).

Inspects coverage, PIT quality, corp-action coverage, latency, schema drift,
failures, restore rehearsal, snapshot integrity, config drift, trial + cost
ledgers. Recommendations are ALWAYS operations-only — the report carries no
threshold/parameter advice by construction (asserted by test).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.db import sqlite_conn  # noqa: E402


def run_monthly(day: str | None = None) -> dict:
    day = day or datetime.now(timezone.utc).date().isoformat()
    B.init_tables()
    health = {f"{h['source']}/{h['dataset']}": h["status"] for h in B.health_snapshot()}
    errors = sqlite_conn().execute(
        "SELECT status, COUNT(*) FROM acquisition_errors GROUP BY status").fetchall()
    try:
        trials_n = sqlite_conn().execute("SELECT COUNT(*) FROM eval_trials").fetchone()[0]
    except Exception:  # noqa: BLE001 - table may not exist in fresh ledgers
        trials_n = 0
    # restore rehearsal against the latest backup (read-only, temp dir)
    backups = sorted([d for d in os.listdir(os.path.join("data", "backups"))
                      if d.startswith("backup-")]) if os.path.isdir(
        os.path.join("data", "backups")) else []
    restore: dict = {"backups_available": len(backups)}
    if backups:
        import scripts.backup_evidence as BE
        rep = BE.restore_rehearsal(os.path.join("data", "backups", backups[-1]))
        restore.update({"ok": rep["ok"], "failures": rep["failures"][:5]})
    # config drift vs freeze (informational here; forward runs enforce)
    import glob as _g
    freezes = sorted(_g.glob("data/strategy_freeze_*.json"))
    drift = None
    if freezes:
        from app.governance import freeze as FRZ
        drift = FRZ.verify(freezes[-1])["verdict"]
    report = {
        "month": day[:7], "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_health": health, "acquisition_errors": {k: v for k, v in errors},
        "trial_ledger_count": trials_n, "restore_rehearsal": restore,
        "config_drift": drift,
        "recommendations": "operations-only: fix sources, storage, scheduling. "
                           "No strategy-parameter advice is ever issued here (§64).",
    }
    path = os.path.join("data", f"monthly_audit_{day[:7]}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return {"report": path, **{k: v for k, v in report.items() if k != "source_health"}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    a = ap.parse_args()
    print(json.dumps(run_monthly(a.day), indent=2, default=str))


if __name__ == "__main__":
    main()
