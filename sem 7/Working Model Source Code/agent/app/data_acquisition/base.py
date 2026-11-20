"""Collector contract + raw-first storage + ledgers (Phase A core).

Every collector: FetchResult contract (§6), FetchStatus enum (§7), raw artifact
store under data/raw/<source>/<dataset>/YYYY/MM/DD with sidecar metadata (§10),
content-addressed dedup (§11), append-only error log (§60), source-health (§55),
backfill checkpoints (§49), acquisition ledger with LIVE/BACKFILL/MANUAL_IMPORT
modes and first-seen timestamps (§§90–92).

Atomic writes (§63): temp + fsync + rename. No strategy logic (§65).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.data_acquisition import util as U
from app.db import sqlite_conn

RAW_ROOT = os.environ.get("DATA_RAW_ROOT", os.path.join("data", "raw"))


class FetchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_SCHEMA_CHANGED = "SOURCE_SCHEMA_CHANGED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    NO_DATA = "NO_DATA"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass
class FetchResult:
    status: FetchStatus
    source: str
    dataset: str
    requested_start: str = ""
    requested_end: str = ""
    records_received: int = 0
    records_written: int = 0
    duplicates: int = 0
    amendments: int = 0
    invalid_records: int = 0
    source_failures: list = field(default_factory=list)
    batch_id: str = ""
    raw_hashes: list = field(default_factory=list)
    manifest_path: str = ""
    started_at: str = ""
    finished_at: str = ""


def init_tables() -> None:
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS acquisition_errors
        (ts TEXT, source TEXT, dataset TEXT, window TEXT, status TEXT,
         http_code INTEGER, message TEXT, retry_count INTEGER, collector_version TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS source_health
        (source TEXT, dataset TEXT, last_success TEXT, latest_record_ts TEXT,
         status TEXT, consecutive_failures INTEGER, expected_freshness TEXT,
         PRIMARY KEY (source, dataset))""")
    c.execute("""CREATE TABLE IF NOT EXISTS backfill_state
        (dataset TEXT PRIMARY KEY, last_completed TEXT, next_window TEXT,
         failure_count INTEGER, last_failure TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS acquisition_ledger
        (artifact_hash TEXT PRIMARY KEY, source TEXT, dataset TEXT,
         ingestion_mode TEXT, first_seen_ts TEXT, publication_ts TEXT,
         n_observations INTEGER, bytes INTEGER)""")
    c.commit()


def log_error(source: str, dataset: str, window: str, status: str,
              message: str, http_code: int | None = None, retry_count: int = 0,
              collector_version: str = "") -> None:
    init_tables()
    sqlite_conn().execute(
        "INSERT INTO acquisition_errors(ts, source, dataset, window, status,"
        " http_code, message, retry_count, collector_version)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (U.utcnow(), source, dataset, window, status, http_code,
         message[:500], retry_count, collector_version))
    sqlite_conn().commit()
    mark_health(source, dataset, ok=False, status=status)


def mark_health(source: str, dataset: str, ok: bool,
                status: str = "SUCCESS", latest_record_ts: str = "",
                expected_freshness: str = "") -> None:
    init_tables()
    row = sqlite_conn().execute(
        "SELECT last_success, consecutive_failures FROM source_health"
        " WHERE source=? AND dataset=?", (source, dataset)).fetchone()
    if ok:
        last_success, fails, state = U.utcnow(), 0, "HEALTHY"
    else:
        last_success = row[0] if row else ""
        fails = (row[1] + 1) if row else 1
        state = ("SCHEMA_CHANGED" if status == "SOURCE_SCHEMA_CHANGED"
                 else "DOWN" if fails >= 5 else "DEGRADED")
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO source_health(source, dataset, last_success,"
        " latest_record_ts, status, consecutive_failures, expected_freshness)"
        " VALUES (?,?,?,?,?,?,?)",
        (source, dataset, last_success, latest_record_ts, state, fails,
         expected_freshness))
    sqlite_conn().commit()


def health_snapshot() -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT source, dataset, last_success, latest_record_ts, status,"
        " consecutive_failures, expected_freshness FROM source_health"
        " ORDER BY source, dataset").fetchall()
    return [{"source": r[0], "dataset": r[1], "last_success": r[2],
             "latest_record_ts": r[3], "status": r[4], "consecutive_failures": r[5],
             "expected_freshness": r[6]} for r in rows]


def store_raw(source: str, dataset: str, day: str, filename: str, data: bytes,
              *, source_url: str = "", content_type: str = "",
              publication_ts: str = "", availability_ts: str = "",
              ingestion_mode: str = "LIVE",
              collector_version: str = "") -> dict:
    """Atomic raw-first store (§§9–11, §63). Returns artifact record with sidecar.
    Same bytes -> same hash: payload file written once, re-observation recorded
    in the acquisition ledger (first_seen preserved forever, §§90–91)."""
    import datetime as _dt
    init_tables()
    digest = U.sha256_bytes(data)
    y, m, d = day[:4], day[5:7], day[8:10]
    directory = os.path.join(RAW_ROOT, source, dataset, y, m, d)
    os.makedirs(directory, exist_ok=True)
    stored_name = f"{digest[:16]}_{filename}"
    path = os.path.join(directory, stored_name)
    is_new = not os.path.exists(path)
    if is_new:
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    now = U.utcnow()
    sidecar = {"source": source, "dataset": dataset, "source_url_or_identifier": source_url,
               "requested_at": now, "response_timestamp": now,
               "content_type": content_type, "content_length": len(data),
               "sha256": digest, "filename": stored_name,
               "publication_timestamp": publication_ts,
               "availability_timestamp": availability_ts or publication_ts,
               "ingestion_timestamp": now, "collector_version": collector_version,
               "ingestion_mode": ingestion_mode,
               "first_seen_live": ingestion_mode == "LIVE",
               "first_seen_ts": now}
    with open(path + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)
    # ledger: first observation wins for first_seen_ts (never backdated, §90)
    row = sqlite_conn().execute(
        "SELECT n_observations FROM acquisition_ledger WHERE artifact_hash=?",
        (digest,)).fetchone()
    if row:
        sqlite_conn().execute(
            "UPDATE acquisition_ledger SET n_observations = n_observations + 1"
            " WHERE artifact_hash=?", (digest,))
    else:
        sqlite_conn().execute(
            "INSERT INTO acquisition_ledger(artifact_hash, source, dataset, ingestion_mode,"
            " first_seen_ts, publication_ts, n_observations, bytes)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (digest, source, dataset, ingestion_mode, now, publication_ts, 1, len(data)))
    sqlite_conn().commit()
    return {"artifact_id": digest[:16], "sha256": digest, "path": path,
            "duplicate_payload": not is_new, "bytes": len(data), "sidecar": sidecar}


def checkpoint_get(dataset: str) -> dict | None:
    init_tables()
    r = sqlite_conn().execute(
        "SELECT last_completed, next_window, failure_count, last_failure"
        " FROM backfill_state WHERE dataset=?", (dataset,)).fetchone()
    if not r:
        return None
    return {"dataset": dataset, "last_completed": r[0], "next_window": r[1],
            "failure_count": r[2], "last_failure": r[3]}


def checkpoint_set(dataset: str, last_completed: str, next_window: str,
                   failed: bool = False, failure_note: str = "") -> None:
    init_tables()
    row = sqlite_conn().execute(
        "SELECT failure_count FROM backfill_state WHERE dataset=?", (dataset,)).fetchone()
    fails = (row[0] + 1 if failed and row else (1 if failed else 0))
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO backfill_state(dataset, last_completed, next_window,"
        " failure_count, last_failure) VALUES (?,?,?,?,?)",
        (dataset, last_completed, next_window, fails,
         failure_note[:300] if failed else ""))
    sqlite_conn().commit()


class Collector:
    """Base class: contract + manifest + health + error discipline."""
    source_name: str = "unknown"
    dataset_name: str = "unknown"
    collector_version: str = "v1"

    def fetch(self, *, start=None, end=None, incremental: bool = True) -> FetchResult:
        raise NotImplementedError

    def manifest(self, result: FetchResult, raw_artifacts: list,
                 source_failures: list) -> dict:
        return U.build_manifest(
            batch_id=result.batch_id or
            f"{self.source_name}-{self.dataset_name}-{U.utcnow()[:10]}",
            source=self.source_name, dataset=self.dataset_name,
            collector_version=self.collector_version,
            requested_start=result.requested_start, requested_end=result.requested_end,
            started_at=result.started_at, finished_at=result.finished_at,
            status=result.status.value, records_received=result.records_received,
            records_written=result.records_written, duplicates=result.duplicates,
            invalid=result.invalid_records, raw_artifacts=raw_artifacts,
            source_failures=source_failures)
