"""Blind human-label groundwork; model/output fields are structurally refused."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from quantplus_intelligence.research_v3.wave5_common import (
    is_sha256,
    parse_aware_timestamp,
    semantic_sha256,
)


FORBIDDEN_FIELDS = frozenset({
    "model", "model_id", "prediction", "classification", "classifier_output",
    "outcome", "return", "abnormal_return", "price_after", "jev_answer",
})
ALLOWED_FIELDS = frozenset({
    "independent_event_id", "capture_version_id", "reviewer_pseudonym",
    "label_version", "event_type", "materiality", "guidance_change",
    "reviewed_at", "fold_id", "blinded_to_model", "outcome_blind", "notes",
})


@dataclass(frozen=True)
class HumanGoldLabel:
    independent_event_id: str
    capture_version_id: str
    reviewer_pseudonym: str
    label_version: str
    event_type: str
    materiality: int
    guidance_change: str
    reviewed_at: str
    fold_id: str
    blinded_to_model: bool = True
    outcome_blind: bool = True
    notes: str = ""

    def __post_init__(self):
        if not self.blinded_to_model or not self.outcome_blind:
            raise ValueError("gold labels must be model-blind and outcome-blind")
        if not 0 <= self.materiality <= 4:
            raise ValueError("materiality must be 0..4")
        parse_aware_timestamp(self.reviewed_at, "reviewed_at")
        if not self.independent_event_id.startswith("HG-"):
            raise ValueError("independent human event ids use the HG- namespace")
        if not is_sha256(self.capture_version_id):
            raise ValueError("capture_version_id must be an immutable sha256 identity")
        if not self.fold_id or not self.reviewer_pseudonym:
            raise ValueError("fold_id and reviewer pseudonym are required")

    @property
    def label_id(self) -> str:
        return semantic_sha256(asdict(self))


def validate_human_label_payload(payload: Mapping[str, Any]) -> HumanGoldLabel:
    keys = set(payload)
    forbidden = keys & FORBIDDEN_FIELDS
    if forbidden:
        raise ValueError("MODEL_OR_OUTCOME_FIELD_FORBIDDEN:" + ",".join(sorted(forbidden)))
    extras = keys - ALLOWED_FIELDS
    if extras:
        raise ValueError("UNKNOWN_LABEL_FIELD:" + ",".join(sorted(extras)))
    return HumanGoldLabel(**dict(payload))
