"""Bounded, rights-aware official-disclosure collector with injected transport.

No undocumented NSE endpoint is embedded here.  The collector is disabled by
default and requires both operator enablement and explicit source rights before
the transport can be called.  Unit tests use fixture transports only.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from quantplus_intelligence.research_v3.wave5_common import (
    bytes_sha256,
    parse_aware_timestamp,
)

from .contracts import (
    CaptureConfig,
    CaptureOutcome,
    CapturedDisclosureVersion,
    IssuerIdentity,
    RawDisclosureObservation,
    SourceRights,
)
from .store import EventCaptureStore


ALLOWED_CONTENT_TYPES = frozenset({
    "application/json", "application/xml", "text/xml", "application/pdf",
    "text/plain", "text/html",
})
INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now", re.I),
    re.compile(r"classify\s+(this|it)\s+as", re.I),
    re.compile(r"override\s+(the\s+)?(rubric|rules|instructions)", re.I),
)


class CaptureTransport(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout_seconds: float
            ) -> tuple[int, Mapping[str, str], bytes]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class OfficialEventCollector:
    def __init__(
        self,
        *,
        config: CaptureConfig,
        rights: SourceRights,
        identities: Mapping[str, IssuerIdentity],
        store: EventCaptureStore,
        transport: CaptureTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
        archive_dir: str | Path | None = None,
    ):
        self.config = config
        self.rights = rights
        self.identities = {key.upper(): value for key, value in identities.items()}
        self.store = store
        self.transport = transport
        self.clock = clock
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self._requests = 0
        self._source_failures = 0
        self._circuit_open = False

    def _preflight(self) -> CaptureOutcome | None:
        if not self.config.enabled:
            return CaptureOutcome("NOT_CONFIGURED", "COLLECTOR_DISABLED_DEFAULT")
        if self.rights.status == "SOURCE_ACCESS_BLOCKED" \
                or not self.rights.automated_capture_allowed:
            return CaptureOutcome("SOURCE_ACCESS_BLOCKED", "SOURCE_RIGHTS_NOT_GRANTED")
        if self.config.archive_original_bytes \
                and not self.rights.original_bytes_storage_allowed:
            return CaptureOutcome("SOURCE_ACCESS_BLOCKED", "ORIGINAL_BYTES_STORAGE_NOT_PERMITTED")
        if self._circuit_open:
            return CaptureOutcome("CIRCUIT_OPEN", "SOURCE_CIRCUIT_OPEN")
        return None

    def _host_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.scheme == "https" and parts.hostname in set(self.config.allowed_hosts) \
            and parts.username is None and parts.password is None

    def ingest(self, observation: RawDisclosureObservation) -> CaptureOutcome:
        blocked = self._preflight()
        if blocked:
            return blocked
        if not self._host_allowed(observation.source_url):
            return CaptureOutcome("REJECTED", "SOURCE_HOST_NOT_ALLOWLISTED")
        if observation.attachment_url and not self._host_allowed(observation.attachment_url):
            return CaptureOutcome("REJECTED", "ATTACHMENT_HOST_NOT_ALLOWLISTED")
        content_type = observation.content_type.split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            return CaptureOutcome("REJECTED", "CONTENT_TYPE_NOT_ALLOWED")
        if len(observation.content_bytes) > self.config.max_response_bytes:
            return CaptureOutcome("REJECTED", "CONTENT_SIZE_LIMIT_EXCEEDED")
        identity = self.identities.get(observation.symbol.upper())
        if identity is None:
            return CaptureOutcome("REJECTED", "ISSUER_SYMBOL_UNRESOLVED")
        if identity.issuer_id != observation.issuer_id:
            return CaptureOutcome("REJECTED", "MISMATCHED_ISSUER")
        if identity.isin != observation.isin:
            return CaptureOutcome("REJECTED", "WRONG_ISIN")
        if identity.canonical_name.casefold() != observation.issuer_name.strip().casefold():
            return CaptureOutcome("REJECTED", "MISMATCHED_ISSUER_NAME")

        try:
            broadcast = parse_aware_timestamp(
                observation.exchange_broadcast_at, "exchange_broadcast_at")
            if observation.original_publication_at:
                parse_aware_timestamp(observation.original_publication_at,
                                      "original_publication_at")
            if observation.provider_first_seen_at:
                parse_aware_timestamp(observation.provider_first_seen_at,
                                      "provider_first_seen_at")
        except ValueError as exc:
            return CaptureOutcome("REJECTED", "AMBIGUOUS_OR_INVALID_TIMESTAMP:" + str(exc))

        first_seen = self.clock()
        if first_seen.tzinfo is None:
            return CaptureOutcome("REJECTED", "COLLECTOR_CLOCK_MUST_BE_OFFSET_AWARE")
        first_seen = first_seen.astimezone(timezone.utc)
        if first_seen < broadcast.astimezone(timezone.utc):
            return CaptureOutcome("REJECTED", "FIRST_SEEN_BEFORE_EXCHANGE_BROADCAST")
        lag = (first_seen - broadcast.astimezone(timezone.utc)).total_seconds()
        pit_class = ("CONTEMPORANEOUS" if lag <= self.config.contemporaneous_max_lag_seconds
                     else "RETROSPECTIVE_RETRIEVAL")

        text = observation.content_bytes.decode("utf-8-sig", "replace")
        flags = []
        if "\ufffd" in text:
            flags.append("ENCODING_REPLACEMENT_CHARACTER")
        if any(pattern.search(text) for pattern in INJECTION_PATTERNS):
            flags.append("PROMPT_INJECTION_SUSPECTED")
        if any(ord(char) < 9 or 13 < ord(char) < 32 for char in text):
            flags.append("CONTROL_CHARACTERS_PRESENT")

        linked_document_id = (observation.corrects_document_id
                              or observation.provider_document_id)
        prior = self.store.latest_for_provider_document(
            self.rights.source_id, linked_document_id)
        prior_version_id = prior["payload"]["version_id"] if prior else None
        content_hash = bytes_sha256(observation.content_bytes)
        headline_hash = bytes_sha256(observation.headline.encode("utf-8"))
        evidence_storage = "HASH_AND_REFERENCE_ONLY"
        evidence_reference = observation.source_url
        if self.config.archive_original_bytes:
            if self.archive_dir is None:
                return CaptureOutcome("NOT_CONFIGURED", "ARCHIVE_DIRECTORY_NOT_CONFIGURED")
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            path = self.archive_dir / content_hash
            if path.exists() and path.read_bytes() != observation.content_bytes:
                return CaptureOutcome("REJECTED", "CONTENT_HASH_COLLISION")
            if not path.exists():
                path.write_bytes(observation.content_bytes)
            evidence_storage = "IMMUTABLE_BYTES_ARCHIVED_WITH_PERMISSION"
            evidence_reference = str(path)

        version = CapturedDisclosureVersion(
            source_id=self.rights.source_id,
            provider_document_id=observation.provider_document_id,
            issuer_id=observation.issuer_id,
            issuer_name=observation.issuer_name,
            symbol=observation.symbol.upper(),
            isin=observation.isin,
            source_url=observation.source_url,
            category=observation.category,
            headline_sha256=headline_hash,
            content_sha256=content_hash,
            content_type=content_type,
            exchange_broadcast_at=observation.exchange_broadcast_at,
            original_publication_at=observation.original_publication_at,
            provider_first_seen_at=observation.provider_first_seen_at,
            first_local_observation_utc=_iso_utc(first_seen),
            available_at=_iso_utc(first_seen),
            pit_class=pit_class,
            attachment_url=observation.attachment_url,
            attachment_status=observation.attachment_status,
            disclosure_state=observation.disclosure_state,
            corrects_document_id=observation.corrects_document_id,
            prior_version_id=prior_version_id,
            rights_label=self.rights.legal_label,
            evidence_storage=evidence_storage,
            evidence_reference=evidence_reference,
            sanitization_flags=tuple(sorted(flags)),
            model_eligible=not flags,
            maturity_label=("OBSERVED_FORWARD" if pit_class == "CONTEMPORANEOUS"
                            else "HISTORICAL_RETROSPECTIVE"),
        )
        existing = self.store.by_version_id(version.version_id)
        if existing:
            # Preserve the exact first local observation from the immutable first
            # record; a later duplicate cannot rewrite first-seen provenance.
            saved_payload = {
                key: value for key, value in existing["payload"].items()
                if key not in {"disclosure_id", "version_id"}
            }
            saved_payload["sanitization_flags"] = tuple(
                saved_payload.get("sanitization_flags", ()))
            saved = CapturedDisclosureVersion(**saved_payload)
            return CaptureOutcome("DUPLICATE", "EXACT_VERSION_ALREADY_CAPTURED", saved, False)
        _record, appended = self.store.append(version)
        return CaptureOutcome("CAPTURED", "IMMUTABLE_VERSION_APPENDED", version, appended)

    def collect_json_export(self, url: str) -> list[CaptureOutcome]:
        """Fetch one explicitly permitted JSON export through bounded transport."""
        blocked = self._preflight()
        if blocked:
            return [blocked]
        if not self._host_allowed(url):
            return [CaptureOutcome("REJECTED", "SOURCE_HOST_NOT_ALLOWLISTED")]
        if self.transport is None:
            return [CaptureOutcome("NOT_CONFIGURED", "TRANSPORT_NOT_CONFIGURED")]
        if self._requests >= self.config.max_requests_per_run:
            return [CaptureOutcome("REJECTED", "REQUEST_RATE_CAP_REACHED")]
        self._requests += 1
        status, headers, body = self.transport.get(
            url,
            {"Accept": "application/json", "User-Agent": "QuantPlus-W5-Research/1.0"},
            self.config.timeout_seconds,
        )
        if status in (429, 503):
            self._source_failures += 1
            if self._source_failures >= self.config.circuit_failure_threshold:
                self._circuit_open = True
            retry = headers.get("Retry-After") or headers.get("retry-after")
            try:
                retry_seconds = min(300, max(0, int(retry))) if retry is not None else None
            except (TypeError, ValueError):
                retry_seconds = None
            return [CaptureOutcome("RETRYABLE_SOURCE_ERROR", f"HTTP_{status}",
                                   retry_after_seconds=retry_seconds)]
        if status != 200:
            self._source_failures += 1
            if self._source_failures >= self.config.circuit_failure_threshold:
                self._circuit_open = True
            return [CaptureOutcome("REJECTED", f"HTTP_{status}")]
        content_type = str(headers.get("Content-Type", headers.get("content-type", ""))) \
            .split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return [CaptureOutcome("REJECTED", "CONTENT_TYPE_NOT_JSON")]
        declared = headers.get("Content-Length") or headers.get("content-length")
        if declared:
            try:
                if int(declared) > self.config.max_response_bytes:
                    return [CaptureOutcome("REJECTED", "DECLARED_SIZE_LIMIT_EXCEEDED")]
            except ValueError:
                return [CaptureOutcome("REJECTED", "INVALID_CONTENT_LENGTH")]
        if len(body) > self.config.max_response_bytes:
            return [CaptureOutcome("REJECTED", "CONTENT_SIZE_LIMIT_EXCEEDED")]
        try:
            decoded = body.decode("utf-8-sig", "strict")
            data = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return [CaptureOutcome("REJECTED", "ENCODING_OR_JSON_INVALID")]
        if not isinstance(data, list):
            return [CaptureOutcome("REJECTED", "EXPORT_ROOT_NOT_LIST")]
        if len(data) > self.config.max_records_per_run:
            return [CaptureOutcome("REJECTED", "EXPORT_RECORD_CAP_EXCEEDED")]
        outcomes = []
        for item in data:
            if not isinstance(item, dict):
                outcomes.append(CaptureOutcome("REJECTED", "EXPORT_ROW_NOT_OBJECT"))
                continue
            try:
                row = dict(item)
                raw_content = row.pop("content_text").encode("utf-8")
                observation = RawDisclosureObservation(
                    content_bytes=raw_content, **row)
            except (KeyError, TypeError, ValueError) as exc:
                outcomes.append(CaptureOutcome(
                    "REJECTED", "EXPORT_SCHEMA_INVALID:" + type(exc).__name__))
                continue
            outcomes.append(self.ingest(observation))
        return outcomes

    def health(self) -> dict:
        preflight = self._preflight()
        return {
            "pipeline_status": preflight.status if preflight else "CONFIGURED_IDLE",
            "pipeline_reason": preflight.reason if preflight else None,
            "enabled": self.config.enabled,
            "schedule_enabled": self.config.schedule_enabled,
            "source_id": self.rights.source_id,
            "source_rights_status": self.rights.status,
            "requests_this_run": self._requests,
            "circuit_open": self._circuit_open,
            "store": self.store.health(),
            "model_classification_enabled": False,
            "authority": "RESEARCH_ONLY",
        }
