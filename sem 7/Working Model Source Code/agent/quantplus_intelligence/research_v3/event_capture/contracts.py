"""Source-rights, timestamp and immutable-version contracts for event capture."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from quantplus_intelligence.research_v3.wave5_common import (
    parse_aware_timestamp,
    semantic_sha256,
)


RIGHTS_STATUSES = ("NOT_REVIEWED", "REFERENCE_ONLY", "PERMISSION_GRANTED", "SOURCE_ACCESS_BLOCKED")
PIPELINE_STATUSES = (
    "NOT_CONFIGURED",
    "SOURCE_ACCESS_BLOCKED",
    "CAPTURED",
    "DUPLICATE",
    "REJECTED",
    "RETRYABLE_SOURCE_ERROR",
    "CIRCUIT_OPEN",
)
PIT_CLASSES = ("CONTEMPORANEOUS", "RETROSPECTIVE_RETRIEVAL")
DISCLOSURE_STATES = ("ACTIVE", "CORRECTION", "WITHDRAWN")
ATTACHMENT_STATUSES = ("NOT_LISTED", "REFERENCE_ONLY", "AVAILABLE_NOT_FETCHED", "UNAVAILABLE", "ARCHIVED")


@dataclass(frozen=True)
class SourceRights:
    source_id: str
    official_entry_url: str
    terms_url: str
    reviewed_at: str | None
    status: str
    automated_capture_allowed: bool
    original_bytes_storage_allowed: bool
    redistribution_allowed: bool
    legal_label: str
    evidence_note: str

    def __post_init__(self):
        if self.status not in RIGHTS_STATUSES:
            raise ValueError(f"unknown source-rights status {self.status!r}")
        for value in (self.official_entry_url, self.terms_url):
            if urlsplit(value).scheme != "https":
                raise ValueError("source-rights URLs must be HTTPS")
        if self.status != "PERMISSION_GRANTED" and self.automated_capture_allowed:
            raise ValueError("automated capture requires explicit PERMISSION_GRANTED")
        if self.original_bytes_storage_allowed and self.status != "PERMISSION_GRANTED":
            raise ValueError("original-byte storage requires explicit permission")
        if self.reviewed_at is not None:
            parse_aware_timestamp(self.reviewed_at, "reviewed_at")


@dataclass(frozen=True)
class CaptureConfig:
    enabled: bool = False
    schedule_enabled: bool = False
    allowed_hosts: tuple[str, ...] = ("www.nseindia.com", "nsearchives.nseindia.com")
    timeout_seconds: float = 15.0
    max_response_bytes: int = 1_000_000
    max_attachment_bytes: int = 10_000_000
    max_records_per_run: int = 100
    max_requests_per_run: int = 4
    circuit_failure_threshold: int = 3
    contemporaneous_max_lag_seconds: int = 86_400
    archive_original_bytes: bool = False

    def __post_init__(self):
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be within (0,30]")
        if not 1 <= self.max_response_bytes <= 5_000_000:
            raise ValueError("max_response_bytes outside safe bounds")
        if not 1 <= self.max_attachment_bytes <= 25_000_000:
            raise ValueError("max_attachment_bytes outside safe bounds")
        if not 1 <= self.max_records_per_run <= 500:
            raise ValueError("max_records_per_run outside safe bounds")
        if not 1 <= self.max_requests_per_run <= 20:
            raise ValueError("max_requests_per_run outside safe bounds")
        if not 1 <= self.circuit_failure_threshold <= 10:
            raise ValueError("circuit threshold outside safe bounds")
        if self.schedule_enabled and not self.enabled:
            raise ValueError("schedule cannot be enabled while collector is disabled")


@dataclass(frozen=True)
class IssuerIdentity:
    issuer_id: str
    canonical_name: str
    symbol: str
    isin: str
    identity_source: str


@dataclass(frozen=True)
class RawDisclosureObservation:
    provider_document_id: str
    issuer_id: str
    issuer_name: str
    symbol: str
    isin: str
    source_url: str
    category: str
    headline: str
    exchange_broadcast_at: str
    original_publication_at: str | None
    provider_first_seen_at: str | None
    attachment_url: str | None
    attachment_status: str
    disclosure_state: str
    corrects_document_id: str | None
    content_type: str
    content_bytes: bytes

    def __post_init__(self):
        if not self.provider_document_id or not self.issuer_id:
            raise ValueError("provider document and issuer ids are required")
        if self.attachment_status not in ATTACHMENT_STATUSES:
            raise ValueError("unknown attachment status")
        if self.disclosure_state not in DISCLOSURE_STATES:
            raise ValueError("unknown disclosure state")
        if self.disclosure_state == "CORRECTION" and not self.corrects_document_id:
            raise ValueError("a correction must link the corrected document")
        if self.disclosure_state == "WITHDRAWN" and not self.corrects_document_id:
            raise ValueError("a withdrawal must link the withdrawn document")
        if not isinstance(self.content_bytes, bytes):
            raise ValueError("content_bytes must be exact captured bytes")


@dataclass(frozen=True)
class CapturedDisclosureVersion:
    source_id: str
    provider_document_id: str
    issuer_id: str
    issuer_name: str
    symbol: str
    isin: str
    source_url: str
    category: str
    headline_sha256: str
    content_sha256: str
    content_type: str
    exchange_broadcast_at: str
    original_publication_at: str | None
    provider_first_seen_at: str | None
    first_local_observation_utc: str
    available_at: str
    pit_class: str
    attachment_url: str | None
    attachment_status: str
    disclosure_state: str
    corrects_document_id: str | None
    prior_version_id: str | None
    rights_label: str
    evidence_storage: str
    evidence_reference: str | None
    sanitization_flags: tuple[str, ...]
    model_eligible: bool
    maturity_label: str
    authority: str = "RESEARCH_ONLY"

    def __post_init__(self):
        if self.pit_class not in PIT_CLASSES:
            raise ValueError("unknown PIT class")
        if self.authority != "RESEARCH_ONLY":
            raise ValueError("captured evidence has no capital authority")
        broadcast = parse_aware_timestamp(self.exchange_broadcast_at, "exchange_broadcast_at")
        first_seen = parse_aware_timestamp(
            self.first_local_observation_utc, "first_local_observation_utc")
        available = parse_aware_timestamp(self.available_at, "available_at")
        if first_seen < broadcast:
            raise ValueError("first local observation cannot precede exchange broadcast")
        if available < first_seen:
            raise ValueError("availability cannot precede local possession")

    @property
    def disclosure_id(self) -> str:
        return semantic_sha256({
            "source_id": self.source_id,
            "provider_document_id": self.provider_document_id,
            "issuer_id": self.issuer_id,
        })

    @property
    def version_id(self) -> str:
        # Capture time is deliberately excluded: exact re-observation dedupes to
        # the first immutable version and preserves its original first-seen time.
        return semantic_sha256({
            "disclosure_id": self.disclosure_id,
            "content_sha256": self.content_sha256,
            "headline_sha256": self.headline_sha256,
            "exchange_broadcast_at": self.exchange_broadcast_at,
            "disclosure_state": self.disclosure_state,
        })

    def to_payload(self) -> dict:
        payload = asdict(self)
        payload["disclosure_id"] = self.disclosure_id
        payload["version_id"] = self.version_id
        return payload


@dataclass(frozen=True)
class CaptureOutcome:
    status: str
    reason: str
    version: CapturedDisclosureVersion | None = None
    appended: bool = False
    retry_after_seconds: int | None = None

    def __post_init__(self):
        if self.status not in PIPELINE_STATUSES:
            raise ValueError(f"unknown capture outcome {self.status!r}")

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "version": self.version.to_payload() if self.version else None,
            "appended": self.appended,
            "retry_after_seconds": self.retry_after_seconds,
        }


def asof_available(version: CapturedDisclosureVersion, decision_cutoff: str) -> bool:
    """Hard rule: available_at > decision cutoff is always unavailable."""
    return parse_aware_timestamp(version.available_at, "available_at") <= \
        parse_aware_timestamp(decision_cutoff, "decision_cutoff")
