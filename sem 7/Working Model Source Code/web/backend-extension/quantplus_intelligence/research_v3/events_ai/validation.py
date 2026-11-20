"""Strict validation: PIT evidence and SystemOne responses. Fail closed.

Every rejection is a typed problem string (stable uppercase tokens) — never a
silent clamp, never a defaulted favourable answer. Response parsing rejects
NaN/Infinity constants outright (JSON ``NaN`` is not valid JSON here).
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from quantplus_intelligence.research_v3.events_ai.contracts import (
    IssuerEventEvidence, is_sha256)

PROB_SUM_TOLERANCE = 0.02

_TS_FIELDS = ("published_at", "first_seen_at", "available_at", "decision_cutoff")

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions", re.I),
    re.compile(r"disregard\s+(the\s+)?(above|previous|prior)", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now", re.I),
    re.compile(r"override\s+(the\s+)?(rubric|instructions|rules)", re.I),
    re.compile(r"classify\s+(this|it)\s+as\s+", re.I),
    re.compile(r"answer\s+should\s+be\b", re.I),
    re.compile(r"return\s+the\s+following\s+answer", re.I),
)


def _parse_ts(value: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def evidence_problems(ev: IssuerEventEvidence) -> list[str]:
    """Typed PIT/provenance validation. Empty list == acceptable evidence."""
    problems: list[str] = []
    required = {
        "event_uid": ev.event_uid, "canonical_issuer": ev.canonical_issuer,
        "ticker": ev.ticker, "document_id": ev.document_id,
        "source_uri": ev.source_uri, "provider": ev.provider,
        "capture_method": ev.capture_method, "rights_label": ev.rights_label,
    }
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            problems.append(f"EMPTY_REQUIRED_FIELD:{name}")
    if not is_sha256(ev.source_sha256):
        problems.append("BAD_SHA256:source_sha256")
    if not is_sha256(ev.excerpt_sha256):
        problems.append("BAD_SHA256:excerpt_sha256")
    if not ev.excerpt_text or len(ev.excerpt_text) > 4000:
        problems.append("EXCERPT_LENGTH_INVALID")
    if ev.source_integrity not in ("VERIFIED", "UNVERIFIED", "TAMPERED"):
        problems.append("UNKNOWN_SOURCE_INTEGRITY")
    if ev.source_integrity == "TAMPERED":
        problems.append("SOURCE_TAMPERED")
    if ev.pit_class not in ("CONTEMPORANEOUS", "RETROSPECTIVE", "VENDOR_RECONSTRUCTION"):
        problems.append("UNKNOWN_PIT_CLASS")
    if not ev.ticker_aliases:
        problems.append("NO_TICKER_ALIAS_FOR_CANONICAL")

    stamps = {}
    for name in _TS_FIELDS:
        parsed = _parse_ts(getattr(ev, name))
        if parsed is None:
            problems.append(f"TS_PARSE:{name}")
        stamps[name] = parsed
    if all(v is not None for v in stamps.values()):
        if stamps["first_seen_at"] < stamps["published_at"]:
            problems.append("TS_ORDER:first_seen_before_published")
        if stamps["available_at"] < stamps["published_at"]:
            problems.append("TS_ORDER:available_before_published")
        if stamps["available_at"] > stamps["decision_cutoff"]:
            problems.append("PIT_VIOLATION:available_after_cutoff")
    return problems


def scan_injection(text: str) -> bool:
    """Excerpt text is UNTRUSTED DATA: detect embedded instructions."""
    if not isinstance(text, str):
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def _reject_constant(name: str):
    raise ValueError(f"non-finite JSON constant rejected: {name}")


def parse_response_bytes(raw: bytes) -> Any:
    """Strict JSON parse: NaN / Infinity constants are rejected, not clamped."""
    return raw.decode("utf-8", "strict") and _rejecting_loads(raw)


def _rejecting_loads(raw: bytes) -> Any:
    import json
    return json.loads(raw.decode("utf-8", "strict"), parse_constant=_reject_constant)


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


def validate_systemone_response(
    questions: dict,
    payload: Any,
    allowed_returned_models: frozenset[str] | tuple[str, ...] | list[str],
) -> tuple[dict, list[str]]:
    """Validate a SystemOne response against the exact questions asked.

    Returns ``(parsed, problems)``; ``parsed`` is complete only when
    ``problems`` is empty. Unknown extra decision keys, NaN/Inf, distribution
    mismatches, wrong types and wrong models are all typed rejections.
    """
    problems: list[str] = []
    parsed: dict = {}
    if not isinstance(payload, dict):
        return parsed, ["RESPONSE_NOT_OBJECT"]
    if set(payload.keys()) != {"model", "answers", "usage"}:
        problems.append("EXTRA_OR_MISSING_TOP_LEVEL_KEYS")
        return parsed, problems

    model = payload["model"]
    if not isinstance(model, str) or not model.strip():
        problems.append("RESPONSE_MODEL_INVALID")
    elif model not in set(allowed_returned_models):
        problems.append(f"MODEL_MISMATCH:{model}")
    parsed["model"] = model

    usage = payload["usage"]
    if not isinstance(usage, dict) or set(usage.keys()) != {"input_tokens", "output_tokens"}:
        problems.append("USAGE_INVALID")
    else:
        for key in ("input_tokens", "output_tokens"):
            value = usage[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                problems.append(f"USAGE_INVALID:{key}")
        if not problems or not any(p.startswith("USAGE_INVALID") for p in problems):
            parsed["input_tokens"] = usage["input_tokens"]
            parsed["output_tokens"] = usage["output_tokens"]

    answers = payload["answers"]
    if not isinstance(answers, dict):
        problems.append("ANSWERS_NOT_OBJECT")
        return parsed, problems
    if set(answers.keys()) != set(questions.keys()):
        for name in sorted(set(questions.keys()) - set(answers.keys())):
            problems.append(f"MISSING_ANSWER:{name}")
        for name in sorted(set(answers.keys()) - set(questions.keys())):
            problems.append(f"EXTRA_ANSWER:{name}")
        return parsed, problems

    for name, question in questions.items():
        answer = answers[name]
        qtype = question.get("type")
        if not isinstance(answer, dict) or answer.get("type") != qtype:
            problems.append(f"ANSWER_TYPE_MISMATCH:{name}")
            continue
        if qtype == "noul":
            value = answer.get("noul")
            if not _finite_number(value) or not (0.0 <= float(value) <= 1.0):
                problems.append(f"NOUL_RANGE:{name}")
            else:
                parsed[name] = float(value)
        elif qtype == "choice":
            criteria = question["criteria"]
            probs = answer.get("probabilities")
            if not isinstance(probs, dict) or set(probs.keys()) != set(criteria.keys()):
                problems.append(f"PROBABILITY_KEYS:{name}")
            else:
                bad = [k for k, v in probs.items() if not _finite_number(v)
                       or not (0.0 <= float(v) <= 1.0)]
                if bad:
                    problems.append(f"PROBABILITY_RANGE:{name}")
                else:
                    total = sum(float(v) for v in probs.values())
                    if abs(total - 1.0) > PROB_SUM_TOLERANCE:
                        problems.append(f"PROB_SUM_MISMATCH:{name}")
            if answer.get("choice") not in criteria:
                problems.append(f"UNKNOWN_CHOICE:{name}")
            conf = answer.get("confidence")
            if not _finite_number(conf) or not (0.0 <= float(conf) <= 1.0):
                problems.append(f"CONFIDENCE_RANGE:{name}")
            if not any(p.endswith(f":{name}") for p in problems):
                parsed[name] = {
                    "choice": answer["choice"],
                    "confidence": float(answer["confidence"]),
                    "probabilities": {k: float(v) for k, v in probs.items()},
                }
        elif qtype == "score":
            criteria = question["criteria"]
            n_levels = len(criteria)
            expected_keys = {str(i) for i in range(n_levels)}
            probs = answer.get("probabilities")
            legend = answer.get("legend")
            norm_probs = None
            if isinstance(probs, dict):
                norm_probs = {str(k): v for k, v in probs.items()}
                if set(norm_probs.keys()) != expected_keys:
                    problems.append(f"PROBABILITY_KEYS:{name}")
            else:
                problems.append(f"PROBABILITY_KEYS:{name}")
            if not isinstance(legend, dict) or {str(k) for k in legend.keys()} != expected_keys:
                problems.append(f"LEGEND_KEYS:{name}")
            if norm_probs is not None and set(norm_probs.keys()) == expected_keys:
                bad = [k for k, v in norm_probs.items() if not _finite_number(v)
                       or not (0.0 <= float(v) <= 1.0)]
                if bad:
                    problems.append(f"PROBABILITY_RANGE:{name}")
                else:
                    total = sum(float(v) for v in norm_probs.values())
                    if abs(total - 1.0) > PROB_SUM_TOLERANCE:
                        problems.append(f"PROB_SUM_MISMATCH:{name}")
            score = answer.get("score")
            if not _finite_number(score) or not (0.0 <= float(score) <= n_levels - 1):
                problems.append(f"SCORE_RANGE:{name}")
            conf = answer.get("confidence")
            if not _finite_number(conf) or not (0.0 <= float(conf) <= 1.0):
                problems.append(f"CONFIDENCE_RANGE:{name}")
            if not any(p.endswith(f":{name}") for p in problems):
                parsed[name] = {
                    "score": float(score),
                    "confidence": float(conf),
                    "probabilities": {int(k): float(v) for k, v in norm_probs.items()},
                    "legend": {int(k): v for k, v in legend.items()},
                }
        else:  # defensive: rubric builder never emits this
            problems.append(f"UNSUPPORTED_QUESTION_TYPE:{name}")
    return parsed, problems
