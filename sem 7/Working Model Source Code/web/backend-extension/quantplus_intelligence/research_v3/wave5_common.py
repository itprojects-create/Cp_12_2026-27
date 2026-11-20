"""Small deterministic primitives shared by the Wave 5 research plane.

This module is deliberately stdlib-only.  Semantic identities never include a
wall clock unless the clock is itself part of the evidence contract.  The
runtime application, account book and broker surfaces are not imported here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any


def canonical_json(value: Any) -> str:
    """Return strict, stable JSON suitable for content addressing."""
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    )


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_aware_timestamp(value: str, field: str = "timestamp") -> datetime:
    """Parse an offset-aware ISO timestamp or fail closed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must carry a UTC offset")
    return parsed


def is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )
