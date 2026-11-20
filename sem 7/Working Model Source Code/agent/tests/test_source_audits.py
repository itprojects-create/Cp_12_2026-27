"""P4/P5 audit-script tests: both audits run clean and state coverage honestly."""
from __future__ import annotations

import json
import subprocess


def test_corp_action_audit_runs_empty_but_honest():
    r = subprocess.run(["python", "scripts/audit_corporate_actions.py"],
                       capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    doc = json.load(open("data/corp_action_coverage_20261010.json", encoding="utf-8"))
    assert doc["n_records"] == 0  # production store empty until live collection
    assert "UNKNOWN" in doc["verification_levels"]
    assert "never auto-filled" in doc["note"]


def test_membership_source_audit_quantifies_degeneracy():
    r = subprocess.run(["python", "scripts/audit_pit_membership_sources.py",
                        "--start", "2021-01-01", "--end", "2021-06-01"],
                       capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    doc = json.load(open("data/membership_quality_20261010.json", encoding="utf-8"))
    assert doc["strict_coverage_ratio"] < 0.5  # degeneracy confirmed, not masked
    assert doc["nonstrict_members_avg"] >= 40
    assert "OFFICIAL_SUBSCRIPTION" in doc["source_classes"]
