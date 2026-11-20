"""Deterministic monitor predicates and no-network dry-run scheduler."""
from __future__ import annotations

from datetime import timezone
from typing import Any, Mapping

from quantplus_intelligence.research_v3.wave5_common import parse_aware_timestamp

from .contracts import MonitorCheck


CHECK_DEFINITIONS: dict[str, str] = {
    "DATA_FEED_COVERAGE_FRESHNESS": "coverage and newest source timestamp",
    "EXCHANGE_CALENDAR_VALIDITY": "calendar verification and horizon",
    "FEE_SCHEDULE_EXPIRY": "effective/expiry coverage for evaluation cutoff",
    "CORPORATE_ACTION_COVERAGE": "verified actions for every eligible window",
    "WORKER_HEARTBEAT": "local worker heartbeat freshness and successful state",
    "MISSED_SCHEDULED_JOBS": "expected job receipts versus observed receipts",
    "W3_CANDIDATE_DIAGNOSTIC_DRIFT": "fixed-cutoff candidate diagnostic delta",
    "FORWARD_SIGNAL_AVAILABILITY": "append-only forward signal existence",
    "EVENT_CLASSIFIER_LABEL_STABILITY": "blind label/adjudication stability",
    "JEV_SERVING_MODEL_ALIAS_DRIFT": "requested alias versus returned model identity",
    "RISK_COST_SENSITIVITY": "eligible net result under stressed costs",
}


def _make(
    check_type: str,
    subject_id: str,
    checked_at: str,
    snapshot: Mapping[str, Any],
    *,
    status: str,
    conclusion: str,
    condition: str,
    reason: str,
    synthetic: bool = False,
) -> MonitorCheck:
    return MonitorCheck(
        check_type=check_type, subject_id=subject_id, checked_at=checked_at,
        status=status, conclusion=conclusion, condition=condition,
        evidence=dict(snapshot), reason=reason,
        maturity_label=("ENGINEERING_CHECK_SYNTHETIC" if synthetic
                        else str(snapshot.get("maturity_label", "ECONOMICS_DATA_BLOCKED"))),
        synthetic=synthetic,
    )


def worker_heartbeat_check(
    subject_id: str,
    checked_at: str,
    heartbeat: Mapping[str, Any],
    *,
    max_age_minutes: float,
) -> MonitorCheck:
    now = parse_aware_timestamp(checked_at, "checked_at").astimezone(timezone.utc)
    raw = heartbeat.get("observed_at") or heartbeat.get("last_success_at")
    snapshot = dict(heartbeat)
    snapshot["max_age_minutes"] = max_age_minutes
    if not raw:
        return _make("WORKER_HEARTBEAT", subject_id, checked_at, snapshot,
                     status="FAIL", conclusion="DATA_BLOCKED",
                     condition="HEARTBEAT_MISSING", reason="no heartbeat timestamp")
    try:
        observed = parse_aware_timestamp(str(raw), "heartbeat.observed_at").astimezone(timezone.utc)
    except ValueError:
        return _make("WORKER_HEARTBEAT", subject_id, checked_at, snapshot,
                     status="FAIL", conclusion="DATA_BLOCKED",
                     condition="HEARTBEAT_INVALID", reason="heartbeat timestamp invalid")
    age_minutes = (now - observed).total_seconds() / 60.0
    snapshot["age_minutes"] = age_minutes
    healthy_state = str(heartbeat.get("status", "")).upper() in {"OK", "HEALTHY", "SUCCESS"}
    if age_minutes < 0:
        return _make("WORKER_HEARTBEAT", subject_id, checked_at, snapshot,
                     status="FAIL", conclusion="DATA_BLOCKED",
                     condition="HEARTBEAT_FROM_FUTURE", reason="future heartbeat refused")
    if not healthy_state or age_minutes > max_age_minutes:
        return _make("WORKER_HEARTBEAT", subject_id, checked_at, snapshot,
                     status="FAIL", conclusion="DATA_BLOCKED",
                     condition="HEARTBEAT_STALE_OR_FAILED",
                     reason="worker state failed or heartbeat exceeded policy")
    return _make("WORKER_HEARTBEAT", subject_id, checked_at, snapshot,
                 status="PASS", conclusion="RESEARCH_DIAGNOSTIC",
                 condition="HEARTBEAT_HEALTHY", reason="local heartbeat predicate passed")


def evaluate_standard_check(
    check_type: str,
    subject_id: str,
    checked_at: str,
    snapshot: Mapping[str, Any],
) -> MonitorCheck:
    """Evaluate source facts supplied by a deterministic collector.

    This function does not fetch, classify or calculate financial returns.  A
    caller must supply the source snapshot and maturity label.
    """
    if check_type not in CHECK_DEFINITIONS:
        raise ValueError(f"unsupported standard check {check_type!r}")
    if check_type == "WORKER_HEARTBEAT":
        return worker_heartbeat_check(
            subject_id, checked_at, snapshot,
            max_age_minutes=float(snapshot.get("max_age_minutes", 90)),
        )

    eligible = bool(snapshot.get("eligible", False))
    ok = bool(snapshot.get("ok", False))
    synthetic = bool(snapshot.get("synthetic", False))
    if check_type in {"W3_CANDIDATE_DIAGNOSTIC_DRIFT", "RISK_COST_SENSITIVITY"} \
            and not eligible:
        return _make(check_type, subject_id, checked_at, snapshot,
                     status="DATA_BLOCKED", conclusion="DATA_BLOCKED",
                     condition="ECONOMIC_INPUTS_INELIGIBLE",
                     reason="valid net-return economics are unavailable", synthetic=synthetic)
    if ok:
        conclusion = str(snapshot.get("conclusion", "RESEARCH_DIAGNOSTIC"))
        return _make(check_type, subject_id, checked_at, snapshot,
                     status="PASS", conclusion=conclusion,
                     condition=str(snapshot.get("condition", "CHECK_PASSED")),
                     reason=str(snapshot.get("reason", "deterministic predicate passed")),
                     synthetic=synthetic)
    conclusion = str(snapshot.get("conclusion", "DATA_BLOCKED"))
    return _make(check_type, subject_id, checked_at, snapshot,
                 status="FAIL", conclusion=conclusion,
                 condition=str(snapshot.get("condition", "CHECK_FAILED")),
                 reason=str(snapshot.get("reason", "deterministic predicate failed")),
                 synthetic=synthetic)


def run_dry_schedule(
    journal,
    *,
    subject_id: str,
    checked_at: str,
    snapshots: Mapping[str, Mapping[str, Any]],
    dry_run: bool = True,
    network_enabled: bool = False,
) -> dict:
    if not dry_run or network_enabled:
        raise ValueError("W5 scheduler supports dry_run=True and network_enabled=False only")
    results = []
    for check_type in sorted(CHECK_DEFINITIONS):
        snapshot = snapshots.get(check_type, {
            "ok": False, "eligible": False,
            "condition": "INPUT_NOT_CONFIGURED",
            "reason": "monitor input not configured",
            "maturity_label": "ECONOMICS_DATA_BLOCKED",
        })
        check = evaluate_standard_check(check_type, subject_id, checked_at, snapshot)
        recorded = journal.record_check(check)
        results.append({
            "check_type": check_type,
            "check_id": check.check_id,
            "status": check.status,
            "conclusion": check.conclusion,
            "appended": recorded["check_appended"],
            "alert_created": recorded["alert_created"],
        })
    return {
        "mode": "DRY_RUN_NO_NETWORK",
        "checked_at": checked_at,
        "checks": results,
        "journal_status": journal.status(),
    }
