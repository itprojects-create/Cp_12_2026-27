"""Append-only hash-chained Wave 5 journal with alert deduplication."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Mapping

from quantplus_intelligence.research_v3.wave5_common import (
    canonical_json,
    parse_aware_timestamp,
    semantic_sha256,
)

from .contracts import MonitorCheck, ResearchLineage


GENESIS = "0" * 64
JOURNAL_SCHEMA = "research_v3/living_journal/1"
EVENT_TYPES = (
    "STUDY_REGISTERED",
    "MONITOR_CHECK_RECORDED",
    "CONCLUSION_CHANGED",
    "ALERT_CREATED",
    "ALERT_ACKNOWLEDGED",
    "ALERT_RESOLVED",
    "DELIVERY_ATTEMPT_RECORDED",
)


class JournalIntegrityError(RuntimeError):
    pass


def delivery_readiness(env: Mapping[str, str] | None = None) -> dict:
    """Report configuration only; never exposes, logs or calls the webhook."""
    values = dict(env or {})
    configured = bool(str(values.get("QP_ALERT_WEBHOOK_URL", "")).strip())
    return {
        "destination": "QP_ALERT_WEBHOOK_URL" if configured else None,
        "status": "CONFIGURED_NOT_DELIVERED" if configured else "NOT_CONFIGURED",
        "delivered": False,
        "acknowledged": False,
        "note": "No delivery is claimed until an append-only receipt and acknowledgement exist.",
    }


class LivingResearchJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        rows = []
        for line_number, line in enumerate(
                self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise JournalIntegrityError(
                    f"journal line {line_number} is not valid JSON") from exc
        return rows

    def _event_ids(self) -> dict[str, dict]:
        return {record["event_id"]: record for record in self.records()}

    def _append(self, event_type: str, occurred_at: str, payload: dict,
                semantic_key: dict) -> tuple[dict, bool]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        parse_aware_timestamp(occurred_at, "occurred_at")
        records = self.records()
        if records:
            intact, reason = self.verify_chain()
            if not intact:
                raise JournalIntegrityError("refusing append to invalid chain: " + reason)
        event_id = semantic_sha256({"event_type": event_type, "key": semantic_key})
        existing = next((record for record in records
                         if record.get("event_id") == event_id), None)
        if existing is not None:
            return existing, False
        seq = len(records) + 1
        prev_hash = records[-1]["record_hash"] if records else GENESIS
        record = {
            "journal_schema": JOURNAL_SCHEMA,
            "seq": seq,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "prev_hash": prev_hash,
            "payload": payload,
        }
        record["record_hash"] = semantic_sha256({
            "seq": seq,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "prev_hash": prev_hash,
            "payload": payload,
        })
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(record) + "\n")
        return record, True

    def register_study(self, lineage: ResearchLineage, occurred_at: str) -> tuple[dict, bool]:
        payload = asdict(lineage)
        payload["lineage_id"] = lineage.lineage_id
        return self._append(
            "STUDY_REGISTERED", occurred_at, payload,
            {"lineage_id": lineage.lineage_id},
        )

    def _last_check(self, check: MonitorCheck) -> dict | None:
        matches = [record for record in self.records()
                   if record["event_type"] == "MONITOR_CHECK_RECORDED"
                   and record["payload"]["check_type"] == check.check_type
                   and record["payload"]["subject_id"] == check.subject_id]
        return matches[-1] if matches else None

    def record_check(self, check: MonitorCheck) -> dict:
        """Append a check and, on conclusion drift, exactly one deduped alert."""
        prior = self._last_check(check)
        check_payload = check.semantic_payload()
        check_payload["check_id"] = check.check_id
        check_record, appended = self._append(
            "MONITOR_CHECK_RECORDED", check.checked_at, check_payload,
            {"check_id": check.check_id},
        )
        result = {
            "check_record": check_record,
            "check_appended": appended,
            "delta_record": None,
            "alert_record": None,
            "alert_created": False,
        }
        if not appended or prior is None:
            return result
        before = prior["payload"]["conclusion"]
        after = check.conclusion
        if before == after:
            return result

        delta_payload = {
            "subject_id": check.subject_id,
            "check_type": check.check_type,
            "before_conclusion": before,
            "after_conclusion": after,
            "before_check_id": prior["payload"]["check_id"],
            "after_check_id": check.check_id,
            "before_event_hash": prior["record_hash"],
            "after_event_hash": check_record["record_hash"],
            "synthetic": check.synthetic,
            "maturity_label": check.maturity_label,
        }
        delta_record, _ = self._append(
            "CONCLUSION_CHANGED", check.checked_at, delta_payload,
            {"before_check_id": prior["payload"]["check_id"],
             "after_check_id": check.check_id},
        )
        result["delta_record"] = delta_record
        condition = f"CONCLUSION_CHANGED:{before}->{after}"
        alert_id = semantic_sha256({
            "subject_id": check.subject_id,
            "check_type": check.check_type,
            "condition": condition,
        })
        severity = "HIGH" if after == "REJECTED" else "MEDIUM"
        alert_payload = {
            "alert_id": alert_id,
            "subject_id": check.subject_id,
            "check_type": check.check_type,
            "severity": severity,
            "created_at": check.checked_at,
            "first_seen_event_hash": delta_record["record_hash"],
            "condition_trigger": condition,
            "evidence_hash": check.evidence_hash,
            "acknowledgement_status": "UNACKNOWLEDGED",
            "resolution_status": "OPEN",
            "delivery_status": "NOT_CONFIGURED",
            "synthetic": check.synthetic,
            "maturity_label": check.maturity_label,
        }
        alert_record, alert_appended = self._append(
            "ALERT_CREATED", check.checked_at, alert_payload,
            {"alert_id": alert_id, "first_seen_event_hash": delta_record["record_hash"]},
        )
        result["alert_record"] = alert_record
        result["alert_created"] = alert_appended
        return result

    def acknowledge(self, alert_id: str, occurred_at: str, actor: str) -> tuple[dict, bool]:
        if not any(record["event_type"] == "ALERT_CREATED"
                   and record["payload"]["alert_id"] == alert_id
                   for record in self.records()):
            raise ValueError("unknown alert_id")
        return self._append(
            "ALERT_ACKNOWLEDGED", occurred_at,
            {"alert_id": alert_id, "actor": actor, "acknowledged_at": occurred_at},
            {"alert_id": alert_id, "actor": actor, "acknowledged_at": occurred_at},
        )

    def resolve(self, alert_id: str, occurred_at: str, reason: str) -> tuple[dict, bool]:
        if not any(record["event_type"] == "ALERT_CREATED"
                   and record["payload"]["alert_id"] == alert_id
                   for record in self.records()):
            raise ValueError("unknown alert_id")
        return self._append(
            "ALERT_RESOLVED", occurred_at,
            {"alert_id": alert_id, "reason": reason, "resolved_at": occurred_at},
            {"alert_id": alert_id, "reason": reason, "resolved_at": occurred_at},
        )

    def record_delivery_attempt(self, alert_id: str, occurred_at: str,
                                readiness: Mapping[str, object], dry_run: bool = True
                                ) -> tuple[dict, bool]:
        if not any(record["event_type"] == "ALERT_CREATED"
                   and record["payload"]["alert_id"] == alert_id
                   for record in self.records()):
            raise ValueError("unknown alert_id")
        status = "DRY_RUN_NOT_DELIVERED" if dry_run else str(
            readiness.get("status", "NOT_CONFIGURED"))
        # No network client exists in this package.  A non-dry attempt without a
        # configured destination is still recorded as NOT_CONFIGURED.
        if not dry_run and not readiness.get("destination"):
            status = "NOT_CONFIGURED"
        payload = {
            "alert_id": alert_id,
            "attempted_at": occurred_at,
            "status": status,
            "delivered": False,
            "destination_configured": bool(readiness.get("destination")),
            "credential_or_url_logged": False,
        }
        return self._append(
            "DELIVERY_ATTEMPT_RECORDED", occurred_at, payload,
            {"alert_id": alert_id, "attempted_at": occurred_at, "status": status},
        )

    def verify_chain(self) -> tuple[bool, str]:
        prev = GENESIS
        for expected_seq, record in enumerate(self.records(), start=1):
            if record.get("seq") != expected_seq:
                return False, f"seq {expected_seq}: sequence mismatch"
            if record.get("prev_hash") != prev:
                return False, f"seq {expected_seq}: prev_hash mismatch"
            expected_hash = semantic_sha256({
                "seq": record["seq"], "event_id": record["event_id"],
                "event_type": record["event_type"],
                "occurred_at": record["occurred_at"],
                "prev_hash": record["prev_hash"], "payload": record["payload"],
            })
            if record.get("record_hash") != expected_hash:
                return False, f"seq {expected_seq}: record_hash mismatch"
            prev = record["record_hash"]
        return True, "chain intact"

    def status(self) -> dict:
        records = self.records()
        created = {r["payload"]["alert_id"]: r for r in records
                   if r["event_type"] == "ALERT_CREATED"}
        acknowledged = {r["payload"]["alert_id"] for r in records
                        if r["event_type"] == "ALERT_ACKNOWLEDGED"}
        resolved = {r["payload"]["alert_id"] for r in records
                    if r["event_type"] == "ALERT_RESOLVED"}
        ok, reason = self.verify_chain()
        return {
            "journal_schema": JOURNAL_SCHEMA,
            "n_events": len(records),
            "head_hash": records[-1]["record_hash"] if records else GENESIS,
            "chain_intact": ok,
            "chain_reason": reason,
            "alerts": [
                {"alert_id": alert_id,
                 "acknowledged": alert_id in acknowledged,
                 "resolved": alert_id in resolved,
                 "condition": record["payload"]["condition_trigger"],
                 "severity": record["payload"]["severity"]}
                for alert_id, record in sorted(created.items())
            ],
            "active_alert_count": sum(1 for alert_id in created if alert_id not in resolved),
        }
