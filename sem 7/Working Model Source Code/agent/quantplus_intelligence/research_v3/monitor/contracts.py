"""Immutable monitoring and experiment-lineage contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from quantplus_intelligence.research_v3.wave5_common import (
    is_sha256,
    parse_aware_timestamp,
    semantic_sha256,
)


CHECK_TYPES = (
    "DATA_FEED_COVERAGE_FRESHNESS",
    "EXCHANGE_CALENDAR_VALIDITY",
    "FEE_SCHEDULE_EXPIRY",
    "CORPORATE_ACTION_COVERAGE",
    "WORKER_HEARTBEAT",
    "MISSED_SCHEDULED_JOBS",
    "W3_CANDIDATE_DIAGNOSTIC_DRIFT",
    "FORWARD_SIGNAL_AVAILABILITY",
    "EVENT_CLASSIFIER_LABEL_STABILITY",
    "JEV_SERVING_MODEL_ALIAS_DRIFT",
    "RISK_COST_SENSITIVITY",
    "CONCLUSION_STATUS",
)
CHECK_STATUSES = ("PASS", "WARN", "FAIL", "INCONCLUSIVE", "DATA_BLOCKED")
CONCLUSIONS = (
    "NOT_TESTED",
    "RUNNABLE_DIAGNOSTIC",
    "DATA_BLOCKED",
    "REJECTED",
    "RESEARCH_DIAGNOSTIC",
    "FORWARD_ELIGIBLE_PENDING_APPROVAL",
    "RETIRED",
    "INCONCLUSIVE",
)


@dataclass(frozen=True)
class ResearchLineage:
    strategy_revision_id: str
    study_id: str
    dataset_hashes: tuple[tuple[str, str], ...]
    source_hashes: tuple[tuple[str, str], ...]
    engine_version: str
    fixed_evaluation_cutoff: str
    challenger_verdict: str
    conclusion: str
    maturity_label: str

    def __post_init__(self):
        if self.conclusion not in CONCLUSIONS:
            raise ValueError(f"unknown research conclusion {self.conclusion!r}")
        for _name, digest in self.dataset_hashes + self.source_hashes:
            if not is_sha256(digest):
                raise ValueError("lineage dataset/source references must be full sha256")

    @property
    def lineage_id(self) -> str:
        return semantic_sha256(asdict(self))


@dataclass(frozen=True)
class MonitorCheck:
    check_type: str
    subject_id: str
    checked_at: str
    status: str
    conclusion: str
    condition: str
    evidence: Mapping[str, Any]
    reason: str
    maturity_label: str
    synthetic: bool = False

    def __post_init__(self):
        if self.check_type not in CHECK_TYPES:
            raise ValueError(f"unknown check type {self.check_type!r}")
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")
        if self.conclusion not in CONCLUSIONS:
            raise ValueError(f"unknown conclusion {self.conclusion!r}")
        parse_aware_timestamp(self.checked_at, "checked_at")
        if not self.subject_id or not self.condition:
            raise ValueError("subject_id and condition are required")

    @property
    def evidence_hash(self) -> str:
        return semantic_sha256(dict(self.evidence))

    def semantic_payload(self) -> dict:
        payload = asdict(self)
        payload["evidence"] = dict(self.evidence)
        payload["evidence_hash"] = self.evidence_hash
        return payload

    @property
    def check_id(self) -> str:
        return semantic_sha256(self.semantic_payload())
