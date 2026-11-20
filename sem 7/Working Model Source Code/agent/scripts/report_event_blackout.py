"""Event-blackout forward report: the §96 13-section format (§77).

Failure analysis before recommendation. Reads a harness artifact +
experiment manifest; works in infancy (integrity/coverage/sample sections
carry the weight until economics exist).

Usage: python scripts/report_event_blackout.py --artifact data/event_blackout_forward_2026-10-10.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.events import report as ER  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--manifest", default="data/event_blackout_v1_manifest.json")
    a = ap.parse_args()
    art = json.load(open(a.artifact, encoding="utf-8"))
    manifest = json.load(open(a.manifest, encoding="utf-8"))
    rep = ER.failure_first(
        sample={"n_events": art.get("n_announcements", 0), "n_companies": 0,
                "n_event_days": 0, "by_type": {},
                "verdict_hint": art.get("verdict", "EVENT_FORWARD_INFANCY")},
        economics=None, coverage=None,
        known_weaknesses=[
            "no live announcement feed yet — sample is zero by construction",
            "effective_ts approximated by publication_ts until meeting-date extraction",
        ])
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": art.get("experiment"), "manifest": manifest["experiment_id"],
        "1_data_integrity": {"manifest_frozen_before_outcomes":
                             manifest["freeze_at"] <= art.get("as_of", "")},
        "2_event_coverage": rep["coverage"],
        "3_classifier_health": {"missing": "no classifications scored yet"},
        "4_pit_verification": {"membership_source_version":
                               manifest.get("membership_source_version")},
        "5_sample_quality": rep["sample"],
        "6_control_metrics": "pending sample",
        "7_candidate_metrics": "pending sample",
        "8_tail_risk_effect": "pending sample",
        "9_opportunity_cost": "pending sample",
        "10_concentration": rep["concentration"],
        "11_failure_analysis": rep["why_fake"],
        "12_verdict": rep["verdict"],
        "13_evidence_still_needed": rep["missing_evidence"] + [
            "live feed rows", "30 eligible events / 10 companies / 20 event-days"],
    }
    path = os.path.join("data", "event_blackout_report_20261010.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    print(json.dumps({k: doc[k] for k in ("12_verdict", "11_failure_analysis")}, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
