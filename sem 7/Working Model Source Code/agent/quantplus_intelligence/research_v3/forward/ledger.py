"""Append-only, tamper-evident forward ledger (W6.2).

Conventions follow the proven W5 journal chain: canonical JSON envelopes,
semantic content hashes, GENESIS prev-hash, append-only writes.  Additions for
forward operation: exactly-once semantics by idempotency key, a cross-process
advisory lock for concurrent writers, torn-tail crash recovery that never
rewrites surviving records, and read-only verification.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quantplus_intelligence.research_v3.wave5_common import (
    canonical_json,
    parse_aware_timestamp,
    semantic_sha256,
)

GENESIS = "0" * 64
LEDGER_SCHEMA = "research_v3/forward_ledger/1"

EVENT_TYPES = frozenset({
    "PREREGISTRATION_SEALED",
    "PREFLIGHT",
    "SESSION_LOCK",
    "SIGNAL_DECISION",
    "NO_SIGNAL",
    "ABSTENTION",
    "ELIGIBILITY_FAILURE",
    "PAPER_INTENT",
    "QUOTE_OBSERVATION",
    "FILL_EVENT",
    "FEE_EVENT",
    "CASH_FLOW",
    "CORPORATE_ACTION_EVENT",
    "VALUATION_MARK",
    "BENCHMARK_MARK",
    "RISK_EVENT",
    "JOB_RECEIPT",
    "REPORT_SNAPSHOT",
    "OUTCOME_OBSERVATION",
    "LEDGER_RECOVERY",
})


class LedgerIntegrityError(RuntimeError):
    pass


class ForwardLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._stale_lock_seconds = 30.0

    # ------------------------------------------------------------------ read
    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        rows = []
        for line_number, line in enumerate(
                self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LedgerIntegrityError(
                    f"ledger line {line_number} is not valid JSON "
                    "(torn tail from a crashed writer; use truncate_torn_tail)"
                ) from exc
        return rows

    def stream_records(self, stream_id: str, event_type: str | None = None) -> list[dict]:
        return [record for record in self.records()
                if record["payload"].get("stream_id") == stream_id
                and (event_type is None or record["event_type"] == event_type)]

    def find_by_idempotency(self, event_id: str) -> dict | None:
        return next((record for record in self.records()
                     if record.get("event_id") == event_id), None)

    # -------------------------------------------------------------- appending
    @staticmethod
    def _process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False

    def _recover_stale_lock(self) -> bool:
        """Recover only a same-host lock owned by a process proven dead."""
        try:
            age = time.time() - self._lock_path.stat().st_mtime
            # Do not open a live writer's lock on Windows: a concurrent reader
            # can transiently prevent that writer from unlinking its own lock.
            if age <= self._stale_lock_seconds:
                return False
            data = json.loads(self._lock_path.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            if (data.get("host") == socket.gethostname()
                    and age > self._stale_lock_seconds
                    and not self._process_alive(pid)):
                recovered = self._lock_path.with_name(
                    self._lock_path.name + f".{pid}.recovered")
                os.replace(self._lock_path, recovered)
                return True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            # Unreadable/ambiguous locks are never removed automatically.
            pass
        return False

    def _acquire_lock(self, token: str) -> None:
        """O_EXCL lock file with bounded retry and conservative stale recovery."""
        for _ in range(600):
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    body = canonical_json({
                        "pid": os.getpid(), "host": socket.gethostname(),
                        "token": token,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    os.write(fd, body.encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return
            except (FileExistsError, PermissionError):
                if self._recover_stale_lock():
                    continue
                time.sleep(0.005)
        raise LedgerIntegrityError("could not acquire the forward ledger write lock")

    def _release_lock(self) -> None:
        for _ in range(100):
            try:
                self._lock_path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                time.sleep(0.005)
        raise LedgerIntegrityError("could not release the forward ledger write lock")

    def append(self, event_type: str, occurred_at: str, payload: dict,
               semantic_key: dict) -> tuple[dict, bool]:
        """Append exactly once for (event_type, semantic_key). Idempotent replays
        return the original record with appended=False."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown forward event type {event_type!r}")
        event_id = semantic_sha256({"event_type": event_type, "key": semantic_key})
        self._acquire_lock(f"{os.getpid()}")
        try:
            records = self.records()
            if records:
                intact, reason = self.verify_chain()
                if not intact:
                    raise LedgerIntegrityError(
                        "refusing append to invalid chain: " + reason)
            existing = next((item for item in records
                             if item.get("event_id") == event_id), None)
            if existing is not None:
                if (existing.get("event_type") != event_type
                        or existing.get("payload") != payload):
                    raise LedgerIntegrityError(
                        "IDEMPOTENCY_CONFLICT: semantic key reused with different payload")
                return existing, False
            occurred = parse_aware_timestamp(occurred_at, "occurred_at")
            if occurred.utcoffset() != timedelta(0):
                raise ValueError("ledger occurred_at must be UTC")
            if records and occurred < parse_aware_timestamp(
                    records[-1]["occurred_at"], "previous occurred_at"):
                raise LedgerIntegrityError(
                    "TIMESTAMP_REGRESSION: append time precedes the current ledger head")
            seq = len(records) + 1
            prev_hash = records[-1]["record_hash"] if records else GENESIS
            record = {
                "ledger_schema": LEDGER_SCHEMA,
                "seq": seq,
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "prev_hash": prev_hash,
                "payload": payload,
            }
            record["record_hash"] = semantic_sha256({
                "seq": seq, "event_id": event_id, "event_type": event_type,
                "occurred_at": occurred_at, "prev_hash": prev_hash,
                "payload": payload,
            })
            encoded = (canonical_json(record) + "\n").encode("utf-8")
            # One binary append while holding the interprocess lock avoids text
            # translation and makes a torn final write detectable.
            with self.path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            return record, True
        finally:
            self._release_lock()

    def append_record(self, event_type: str, record: Any,
                      semantic_key: dict) -> tuple[dict, bool]:
        """Append a typed forward record; payload is the record's payload()."""
        return self.append(event_type, record.recorded_at, record.payload(),
                           semantic_key)

    # ----------------------------------------------------------- verification
    def verify_chain(self) -> tuple[bool, str]:
        prev = GENESIS
        previous_time = None
        for expected_seq, record in enumerate(self.records(), start=1):
            if record.get("seq") != expected_seq:
                return False, f"seq {expected_seq}: sequence mismatch"
            if record.get("prev_hash") != prev:
                return False, f"seq {expected_seq}: prev_hash mismatch"
            expected_hash = semantic_sha256({
                "seq": record["seq"], "event_id": record["event_id"],
                "event_type": record["event_type"],
                "occurred_at": record["occurred_at"],
                "prev_hash": record["prev_hash"], "payload": record["payload"],
            })
            if record.get("record_hash") != expected_hash:
                return False, f"seq {expected_seq}: record_hash mismatch"
            try:
                occurred = parse_aware_timestamp(record["occurred_at"], "occurred_at")
            except (TypeError, ValueError) as exc:
                return False, f"seq {expected_seq}: invalid occurred_at ({exc})"
            if occurred.utcoffset() != timedelta(0):
                return False, f"seq {expected_seq}: occurred_at not UTC"
            if previous_time is not None and occurred < previous_time:
                return False, f"seq {expected_seq}: occurred_at regression"
            previous_time = occurred
            prev = record["record_hash"]
        return True, "chain intact"

    # --------------------------------------------------------------- recovery
    def truncate_torn_tail(self) -> tuple[bool, str]:
        """Crash recovery: remove ONLY an incomplete trailing line, then verify.

        Surviving records are never rewritten.  A removal is real repair, so the
        caller must append a LEDGER_RECOVERY event afterwards.
        """
        self._acquire_lock(f"recovery:{os.getpid()}")
        try:
            if not self.path.is_file():
                return False, "no ledger file"
            raw = self.path.read_bytes()
            if raw.endswith(b"\n") or not raw:
                intact, reason = self.verify_chain()
                return intact, reason
            boundary = raw.rfind(b"\n") + 1
            tail = raw[boundary:]
            try:
                json.loads(tail.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                keep = raw[:boundary]
                action = "torn tail removed"
            else:
                # A complete record may be durable even if the final newline was
                # interrupted. Preserve its bytes and add only the delimiter.
                keep = raw + b"\n"
                action = "complete tail preserved; newline restored"
            temporary = self.path.with_suffix(self.path.suffix + ".recovery.tmp")
            with temporary.open("wb") as handle:
                handle.write(keep)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            intact, reason = self.verify_chain()
            return intact, f"{action}; {reason}"
        finally:
            self._release_lock()

    def head(self) -> str:
        records = self.records()
        return records[-1]["record_hash"] if records else GENESIS

    def status(self) -> dict:
        records = self.records()
        ok, reason = self.verify_chain()
        streams: dict[str, dict] = {}
        for record in records:
            stream_id = record["payload"].get("stream_id")
            if not stream_id:
                continue
            info = streams.setdefault(
                stream_id, {"events": 0, "event_types": {}})
            info["events"] += 1
            info["event_types"][record["event_type"]] = \
                info["event_types"].get(record["event_type"], 0) + 1
        return {
            "ledger_schema": LEDGER_SCHEMA,
            "n_events": len(records),
            "head_hash": self.head(),
            "chain_intact": ok,
            "chain_reason": reason,
            "streams": streams,
        }


class SqliteForwardLedger:
    """Transactional runtime ledger with a deterministic JSONL audit export.

    Each append uses ``BEGIN IMMEDIATE`` plus UNIQUE(event_id), so concurrent
    service processes get exactly-once semantics from SQLite itself. The JSONL
    file required for review is an ordered, byte-stable export; it is not a
    second mutable source of truth.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS forward_events (
                    seq INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    stream_id TEXT,
                    record_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_forward_stream
                    ON forward_events(stream_id, seq);
            """)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def records(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT record_json FROM forward_events ORDER BY seq").fetchall()
        finally:
            conn.close()
        return [json.loads(row[0]) for row in rows]

    def stream_records(self, stream_id: str, event_type: str | None = None) -> list[dict]:
        return [record for record in self.records()
                if record["payload"].get("stream_id") == stream_id
                and (event_type is None or record["event_type"] == event_type)]

    def find_by_idempotency(self, event_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT record_json FROM forward_events WHERE event_id=?", (event_id,)).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None

    def append(self, event_type: str, occurred_at: str, payload: dict,
               semantic_key: dict) -> tuple[dict, bool]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown forward event type {event_type!r}")
        occurred = parse_aware_timestamp(occurred_at, "occurred_at")
        if occurred.utcoffset() != timedelta(0):
            raise ValueError("ledger occurred_at must be UTC")
        event_id = semantic_sha256({"event_type": event_type, "key": semantic_key})
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT record_json FROM forward_events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                record = json.loads(existing[0])
                if record["event_type"] != event_type or record["payload"] != payload:
                    raise LedgerIntegrityError(
                        "IDEMPOTENCY_CONFLICT: semantic key reused with different payload")
                conn.commit()
                return record, False
            last = conn.execute(
                "SELECT seq, record_hash, occurred_at FROM forward_events "
                "ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (last[0] + 1) if last else 1
            prev_hash = last[1] if last else GENESIS
            if last and occurred < parse_aware_timestamp(last[2], "previous occurred_at"):
                raise LedgerIntegrityError(
                    "TIMESTAMP_REGRESSION: append time precedes the current ledger head")
            record = {
                "ledger_schema": LEDGER_SCHEMA, "seq": seq,
                "event_id": event_id, "event_type": event_type,
                "occurred_at": occurred_at, "prev_hash": prev_hash,
                "payload": payload,
            }
            record["record_hash"] = semantic_sha256({
                "seq": seq, "event_id": event_id, "event_type": event_type,
                "occurred_at": occurred_at, "prev_hash": prev_hash, "payload": payload})
            conn.execute(
                "INSERT INTO forward_events(seq,event_id,event_type,occurred_at,stream_id,"
                "record_json,record_hash) VALUES (?,?,?,?,?,?,?)",
                (seq, event_id, event_type, occurred_at, payload.get("stream_id"),
                 canonical_json(record), record["record_hash"]))
            conn.commit()
            return record, True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def append_record(self, event_type: str, record: Any,
                      semantic_key: dict) -> tuple[dict, bool]:
        return self.append(event_type, record.recorded_at, record.payload(), semantic_key)

    def verify_chain(self) -> tuple[bool, str]:
        # Reuse the JSONL verifier over the in-memory ordered record list.
        prev = GENESIS
        previous_time = None
        for expected_seq, record in enumerate(self.records(), start=1):
            if record.get("seq") != expected_seq:
                return False, f"seq {expected_seq}: sequence mismatch"
            if record.get("prev_hash") != prev:
                return False, f"seq {expected_seq}: prev_hash mismatch"
            expected = semantic_sha256({
                "seq": record["seq"], "event_id": record["event_id"],
                "event_type": record["event_type"], "occurred_at": record["occurred_at"],
                "prev_hash": record["prev_hash"], "payload": record["payload"]})
            if record.get("record_hash") != expected:
                return False, f"seq {expected_seq}: record_hash mismatch"
            occurred = parse_aware_timestamp(record["occurred_at"], "occurred_at")
            if previous_time is not None and occurred < previous_time:
                return False, f"seq {expected_seq}: occurred_at regression"
            previous_time = occurred
            prev = record["record_hash"]
        return True, "chain intact"

    def head(self) -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT record_hash FROM forward_events ORDER BY seq DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return row[0] if row else GENESIS

    def export_jsonl(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("wb") as handle:
            for record in self.records():
                handle.write((canonical_json(record) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination

    def status(self) -> dict:
        records = self.records()
        ok, reason = self.verify_chain()
        streams: dict[str, dict] = {}
        for record in records:
            stream_id = record["payload"].get("stream_id")
            if not stream_id:
                continue
            info = streams.setdefault(stream_id, {"events": 0, "event_types": {}})
            info["events"] += 1
            info["event_types"][record["event_type"]] = \
                info["event_types"].get(record["event_type"], 0) + 1
        return {"ledger_schema": LEDGER_SCHEMA, "storage": "SQLITE_TRANSACTIONAL",
                "n_events": len(records), "head_hash": self.head(),
                "chain_intact": ok, "chain_reason": reason, "streams": streams}
