"""Default-disabled official issuer-disclosure capture foundation (Wave 5)."""

from .collector import OfficialEventCollector
from .contracts import (
    CaptureConfig,
    CaptureOutcome,
    CapturedDisclosureVersion,
    IssuerIdentity,
    RawDisclosureObservation,
    SourceRights,
    asof_available,
)
from .goldset import HumanGoldLabel, validate_human_label_payload
from .store import EventCaptureStore

__all__ = [
    "CaptureConfig",
    "CaptureOutcome",
    "CapturedDisclosureVersion",
    "EventCaptureStore",
    "HumanGoldLabel",
    "IssuerIdentity",
    "OfficialEventCollector",
    "RawDisclosureObservation",
    "SourceRights",
    "asof_available",
    "validate_human_label_payload",
]
