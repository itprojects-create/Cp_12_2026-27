"""P9 ritual tests: order, fail-closed judging, .md report, monthly audit purity."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
import weekly_ritual as WR  # noqa: E402


def test_weekly_dry_run_order_and_report():
    rec = WR.run_weekly(day="2026-10-10", dry_run=True)
    assert rec["order"] == ["1_health", "2_snapshots", "3_settle", "4_experiment_evidence",
                            "5_judge", "6_calibration", "7_memory", "8_foundry",
                            "9_report", "10_freeze", "11_backup"]
    assert rec["steps"]["5_judge"]["verdict"] in ("judged", "NO_JUDGMENT")
    assert rec["steps"]["8_foundry"]["allowed"] is False  # dry-run never allows
    assert rec["steps"]["6_calibration"]["calibration"]["status"] in (
        "INSUFFICIENT_CALIBRATION_SAMPLE", "REPORTED")
    assert "Failure-first" in WR.render_weekly_md(rec, {"judged": [], "allocation": {}})


def test_monthly_audit_never_optimizes(tmp_path):
    import monthly_audit as MA
    out = MA.run_monthly("2026-10-10")
    doc = json.load(open(out["report"], encoding="utf-8"))
    assert doc["recommendations"].startswith("operations-only")
    blob = json.dumps(doc).lower()
    for phrase in ("change momentum", "change vix", "ranking weights", "retune",
                   "increase topk", "lower threshold"):
        assert phrase not in blob
    assert "trial_ledger_count" in doc and "restore_rehearsal" in doc
    os.remove(out["report"])
