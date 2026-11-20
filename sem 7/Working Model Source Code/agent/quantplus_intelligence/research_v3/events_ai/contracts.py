"""Typed, versioned, deterministic contracts for issuer-event evidence.

Semantic identity rules (blueprint §10.2 / W4 handoff):
- ``event_id`` is derived ONLY from semantic source identity (issuer, ticker,
  document id, source/excerpt hashes, publication and availability stamps and
  the evidence provider). Capture metadata (first_seen_at, capture_method),
  rights labels and the mutable integrity status are deliberately excluded so
  re-captures and integrity upgrades cannot fork the semantic event.
- ``classification_id`` derives from semantic source + model + rubric identity:
  (event_id, provider, returned model, rubric hash, request hash, raw response
  hash). Wall-clock fields (created_at, latency) are excluded — two clean
  offline runs must produce the same ids.
- ``first_seen_at`` is never backdated: it is our capture/first-sight time and
  must be >= published_at. RETROSPECTIVE / VENDOR_RECONSTRUCTION evidence is
  stored but is never forward-eligible.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping

ISSUER_SCHEMA_VERSION = "events_ai/evidence/1"
CLASSIFICATION_SCHEMA_VERSION = "events_ai/classification/1"

SOURCE_INTEGRITY = ("VERIFIED", "UNVERIFIED", "TAMPERED")
PIT_CLASSES = ("CONTEMPORANEOUS", "RETROSPECTIVE", "VENDOR_RECONSTRUCTION")

EXCERPT_MAX_CHARS = 4000          # bounded official excerpt, full doc never stored

FORWARD_ELIGIBLE_PIT = ("CONTEMPORANEOUS",)


def canonical_json(obj) -> str:
    """Deterministic JSON text: sorted keys, tight separators, ASCII, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True)
class IssuerEventEvidence:
    """Source truth for one official issuer announcement (never model output).

    ``ticker`` is the canonical symbol; ``ticker_aliases`` carries known rename
    aliases so post-rename documents resolve to the same instrument WITHOUT
    inventing any dated action (alias resolution is pure identity mapping).
    """

    event_uid: str                      # operator-stable capture uid
    canonical_issuer: str
    ticker: str
    ticker_aliases: tuple[str, ...]
    document_id: str
    source_uri: str
    source_sha256: str                  # hash of the captured document bytes
    excerpt_sha256: str                 # hash of the exact excerpt text
    excerpt_text: str                   # bounded official excerpt
    published_at: str                   # issuer's official publication stamp
    first_seen_at: str                  # our capture/first-sight time (>= published_at)
    available_at: str                   # admissible-at time (<= decision_cutoff)
    decision_cutoff: str                # evaluation decision-time cutoff
    provider: str                       # e.g. nse_official_announcements
    capture_method: str
    rights_label: str
    source_integrity: str               # VERIFIED | UNVERIFIED | TAMPERED
    pit_class: str                      # CONTEMPORANEOUS | RETROSPECTIVE | VENDOR_RECONSTRUCTION

    def semantic_payload(self) -> dict:
        return {
            "schema_version": ISSUER_SCHEMA_VERSION,
            "canonical_issuer": self.canonical_issuer,
            "ticker": self.ticker,
            "document_id": self.document_id,
            "source_sha256": self.source_sha256,
            "excerpt_sha256": self.excerpt_sha256,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "provider": self.provider,
        }

    @property
    def event_id(self) -> str:
        return sha256_text(canonical_json(self.semantic_payload()))

    @property
    def forward_eligible(self) -> bool:
        return self.pit_class in FORWARD_ELIGIBLE_PIT


@dataclass(frozen=True)
class IssuerAliasMap:
    """Pure identity mapping: alias -> canonical ticker. Never invents actions."""

    aliases: Mapping[str, str]

    def resolve(self, symbol: str) -> str | None:
        canonical = self.aliases.get(symbol.strip().upper())
        if canonical is None:
            return None
        # Chained aliases are followed at most once; a map aliasing to itself
        # is a configuration error and resolves to the canonical value.
        return canonical

    def aliases_of(self, ticker: str) -> tuple[str, ...]:
        return tuple(sorted(a for a, c in self.aliases.items() if c == ticker.upper()))


CLASSIFICATION_STATUSES = ("VALID", "ABSTAIN", "NEEDS_REVIEW", "INVALID", "UNAVAILABLE")


@dataclass(frozen=True)
class EventClassification:
    """One model judgment over one evidence record (recorded BEFORE outcomes).

    Statuses:
      VALID         — response validated, evidence clean, confidence above review bar
      ABSTAIN       — the rubric itself abstained (e.g. ambiguous evidence policy)
      NEEDS_REVIEW  — low confidence, suspected injection or disagreement
      INVALID       — contract violation (bad keys, bad distribution, wrong model)
      UNAVAILABLE   — provider off / budget / transport / circuit open (no judgment)
    """

    event_uid: str
    event_id: str
    provider: str                       # typesafe_direct | experientiallabs_gateway | fake
    model_id: str                       # the model ACTUALLY returned by the provider
    requested_model: str
    rubric_sha256: str
    request_payload_sha256: str
    raw_response_sha256: str
    status: str
    status_reason: str | None
    event_type: str | None = None
    event_type_probabilities: Mapping[str, float] = field(default_factory=dict)
    event_type_confidence: float | None = None
    explicit_guidance_change: float | None = None     # noul probability of YES
    materiality_score: float | None = None
    materiality_confidence: float | None = None
    materiality_probabilities: Mapping[int, float] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate_usd: float = 0.0
    latency_ms: int | None = None

    def semantic_payload(self) -> dict:
        return {
            "schema_version": CLASSIFICATION_SCHEMA_VERSION,
            "event_id": self.event_id,
            "provider": self.provider,
            "model_id": self.model_id,
            "requested_model": self.requested_model,
            "rubric_sha256": self.rubric_sha256,
            "request_payload_sha256": self.request_payload_sha256,
            "raw_response_sha256": self.raw_response_sha256,
        }

    @property
    def classification_id(self) -> str:
        return sha256_text(canonical_json(self.semantic_payload()))

    def to_store_payload(self) -> dict:
        """Compact, redacted, secret-free record for the append-only store."""
        return {
            "classification_schema": CLASSIFICATION_SCHEMA_VERSION,
            "classification_id": self.classification_id,
            "event_uid": self.event_uid,
            "event_id": self.event_id,
            "provider": self.provider,
            "model_id": self.model_id,
            "requested_model": self.requested_model,
            "rubric_sha256": self.rubric_sha256,
            "request_payload_sha256": self.request_payload_sha256,
            "raw_response_sha256": self.raw_response_sha256,
            "status": self.status,
            "status_reason": self.status_reason,
            "event_type": self.event_type,
            "event_type_probabilities": dict(self.event_type_probabilities),
            "event_type_confidence": self.event_type_confidence,
            "explicit_guidance_change": self.explicit_guidance_change,
            "materiality_score": self.materiality_score,
            "materiality_confidence": self.materiality_confidence,
            "materiality_probabilities": {
                str(k): v for k, v in self.materiality_probabilities.items()},
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
            "cost_estimate_usd": self.cost_estimate_usd,
            "latency_ms": self.latency_ms,
        }


def is_sha256(value: str) -> bool:
    return _is_sha256(value)
