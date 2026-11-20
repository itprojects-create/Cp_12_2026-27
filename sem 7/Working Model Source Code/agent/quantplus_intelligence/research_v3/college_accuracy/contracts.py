"""Immutable contracts for the post-W6 college accuracy evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SPEC_SCHEMA = "research_v3/college_directional_accuracy_spec/1"
EVIDENCE_TIER = "HISTORICAL_OOF_DEVELOPMENT"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def compute_spec_hash(spec: dict) -> str:
    payload = dict(spec)
    payload.pop("spec_payload_sha256", None)
    return semantic_hash(payload)


def verify_sealed_spec(spec: dict) -> tuple[bool, str]:
    if spec.get("schema") != SPEC_SCHEMA:
        return False, "unexpected schema"
    expected = spec.get("spec_payload_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False, "missing spec payload hash"
    actual = compute_spec_hash(spec)
    if actual != expected:
        return False, f"spec hash mismatch: expected {expected}, actual {actual}"
    if spec.get("evidence_tier") != EVIDENCE_TIER:
        return False, "evidence tier must remain HISTORICAL_OOF_DEVELOPMENT"
    holdout = spec.get("holdout_policy", {})
    if holdout.get("revealed_w2_holdout") != ["2024-06-21", "2026-09-17"]:
        return False, "revealed W2 holdout quarantine missing"
    if holdout.get("fresh_sealed_holdout") != "NEW_SEALED_HOLDOUT_UNAVAILABLE":
        return False, "fresh sealed holdout must remain unavailable"
    return True, "sealed spec valid"


def write_sealed_spec(path: str | Path, payload: dict) -> dict:
    path = Path(path)
    spec = dict(payload)
    spec["schema"] = SPEC_SCHEMA
    spec["spec_payload_sha256"] = compute_spec_hash(spec)
    text = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"refusing to replace a different sealed evaluation spec: {path}")
    path.write_text(text, encoding="utf-8", newline="\n")
    return spec
