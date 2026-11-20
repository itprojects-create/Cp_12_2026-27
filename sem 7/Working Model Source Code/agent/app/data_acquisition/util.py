"""Bounded retry helper + hashing + quality + manifests for collectors."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime, timezone

from app.data_acquisition.http import _backoff


def with_retries(fn: Callable[[], object], *, retries: int = 3,
                 what: str = "operation") -> object:
    """Bounded retry for non-HTTP fallible steps (parsing, unzip)."""
    if not 0 <= retries <= 10:
        raise ValueError("retries must be in [0,10]")
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(_backoff(attempt))
    raise RuntimeError(f"{what} failed after {retries} retries: {last}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_id(data: bytes) -> str:
    """Content address: same bytes -> same id, payload never duplicated (§11)."""
    return sha256_bytes(data)[:16]


def schema_fingerprint(columns: list[str], types: dict[str, str] | None = None,
                       namespace: str = "") -> str:
    """§58: fingerprint of column names/order/types (+XBRL namespace)."""
    return sha256_bytes(json.dumps(
        {"columns": list(columns), "types": dict(sorted((types or {}).items())),
         "namespace": namespace}).encode())[:16]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_manifest(**kw) -> dict:
    """§59 collection manifest. Hash covers content (excluding itself)."""
    base = {"batch_id": kw.get("batch_id", ""),
            "source": kw.get("source", ""), "dataset": kw.get("dataset", ""),
            "collector_version": kw.get("collector_version", ""),
            "requested_start": kw.get("requested_start", ""),
            "requested_end": kw.get("requested_end", ""),
            "started_at": kw.get("started_at", ""), "finished_at": kw.get("finished_at", ""),
            "status": kw.get("status", "SUCCESS"),
            "records_received": kw.get("records_received", 0),
            "records_written": kw.get("records_written", 0),
            "duplicates": kw.get("duplicates", 0),
            "invalid": kw.get("invalid", 0),
            "raw_artifacts": kw.get("raw_artifacts", []),
            "source_failures": kw.get("source_failures", [])}
    base["manifest_hash"] = sha256_bytes(
        json.dumps(base, sort_keys=True).encode())[:16]
    return base


def quality_report(expected: int, received: int, *, invalid: int = 0,
                   duplicates: int = 0, missing_fields: int = 0,
                   pit_verified: int = 0, pit_partial: int = 0,
                   pit_unknown: int = 0) -> dict:
    """§45 quality metrics. Detection only — never repairs data."""
    total = received or 1
    return {"expected_records": expected, "received_records": received,
            "coverage": round(received / max(expected, 1), 4),
            "duplicate_rate": round(duplicates / total, 4),
            "invalid_record_rate": round(invalid / total, 4),
            "missing_fields": missing_fields,
            "pit_verified_pct": round(100 * pit_verified / total, 2),
            "pit_partial_pct": round(100 * pit_partial / total, 2),
            "pit_unknown_pct": round(100 * pit_unknown / total, 2)}
