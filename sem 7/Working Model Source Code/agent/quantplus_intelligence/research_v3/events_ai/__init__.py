"""W4 events_ai subpackage (blueprint §10): typed PIT issuer-event evidence and
a validated Jev (System One) adapter — RESEARCH_ONLY, never trade authority.

Positioning: this package produces *event classifications and cited qualitative
evidence* for research. It emits no BUY/SELL authority, no order, balance,
fee or risk-policy mutation, and its probabilities are NOT stock-return
probabilities. The Jev event-type probability is a probability that the official
excerpt belongs to an event class — nothing more.

Reuse discipline (no second archive / committee / order service):
- V2 deterministic event taxonomy is reused read-only via
  ``quantplus_intelligence.forecast.events`` (keyword baseline adapter);
- W2 ``research_v3.lab`` primitives (``fingerprint``, ``ResearchJournal``) are
  reused for run identity and registration;
- W3 ``quantlab`` numeric control is NOT imported here except by the W4
  regression check, so Jev can never perturb the frozen numeric plane.

Fail-closed everywhere: provider disabled, budget exhausted, auth failure,
malformed answers, model mismatch, stale evidence, wrong issuer, injected
instructions — all degrade to ABSTAIN / NEEDS_REVIEW / INVALID / UNAVAILABLE,
never to a favourable default.
"""
from __future__ import annotations

from quantplus_intelligence.research_v3.events_ai.contracts import (
    CLASSIFICATION_SCHEMA_VERSION, ISSUER_SCHEMA_VERSION, EventClassification,
    IssuerAliasMap, IssuerEventEvidence, canonical_json, sha256_text)
from quantplus_intelligence.research_v3.events_ai.validation import (
    evidence_problems, scan_injection, validate_systemone_response)

__all__ = [
    "ISSUER_SCHEMA_VERSION", "CLASSIFICATION_SCHEMA_VERSION",
    "EventClassification", "IssuerAliasMap", "IssuerEventEvidence",
    "canonical_json", "sha256_text", "evidence_problems", "scan_injection",
    "validate_systemone_response",
]
