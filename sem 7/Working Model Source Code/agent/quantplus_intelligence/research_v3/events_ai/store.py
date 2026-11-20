"""Append-only event-classification store with a sha256 hash chain.

Properties (W4 handoff B7, test 8):
- records are appended BEFORE outcomes exist (no outcome fields exist here);
- append is idempotent per ``classification_id`` — re-registering the same
  semantic classification never duplicates a record (the W3 journal-era
  re-append bug pattern is explicitly guarded against);
- every record carries ``prev_hash``/``record_hash``; ``verify_chain`` proves
  append-only integrity end to end;
- payloads are compact and redacted: only sha256 references to raw responses,
  never raw bodies, never credentials, never full source documents.
"""
from __future__ import annotations

import json
from pathlib import Path

from quantplus_intelligence.research_v3.events_ai.contracts import (
    EventClassification, canonical_json, sha256_text)

STORE_SCHEMA = "events_ai/store/1"


class EventClassificationStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._seq = self._last_seq()
        self._last_hash = self._last_record_hash()
        self._ids: dict[str, int] = self._index_ids()

    # -- append --------------------------------------------------------------
    def append(self, classification: EventClassification) -> tuple[int, bool]:
        """Append one classification. Returns (seq, appended_flag).

        A classification_id already present returns its existing seq without
        writing (dedup), keeping the store append-only AND collision-free.
        """
        payload = classification.to_store_payload()
        classification_id = payload["classification_id"]
        existing = self._ids.get(classification_id)
        if existing is not None:
            return existing, False
        self._seq += 1
        record = {
            "store_schema": STORE_SCHEMA,
            "seq": self._seq,
            "prev_hash": self._last_hash,
            "payload": payload,
        }
        record_hash = sha256_text(canonical_json(
            {"seq": record["seq"], "prev_hash": record["prev_hash"],
             "payload": record["payload"]}))
        record["record_hash"] = record_hash
        line = json.dumps(record, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        self._last_hash = record_hash
        self._ids[classification_id] = self._seq
        return self._seq, True

    # -- introspection -------------------------------------------------------
    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def by_classification_id(self, classification_id: str) -> dict | None:
        seq = self._ids.get(classification_id)
        if seq is None:
            return None
        for record in self.records():
            if record["seq"] == seq:
                return record
        return None

    def verify_chain(self) -> tuple[bool, int | None]:
        """Returns (ok, first_bad_seq). Recomputes every record hash in order."""
        prev = ""
        for record in self.records():
            expected = sha256_text(canonical_json(
                {"seq": record["seq"], "prev_hash": prev, "payload": record["payload"]}))
            if record.get("prev_hash") != prev or record.get("record_hash") != expected:
                return False, record["seq"]
            prev = record["record_hash"]
        return True, None

    # -- internals -----------------------------------------------------------
    def _last_seq(self) -> int:
        records = self.records()
        return records[-1]["seq"] if records else 0

    def _last_record_hash(self) -> str:
        records = self.records()
        return records[-1]["record_hash"] if records else ""

    def _index_ids(self) -> dict[str, int]:
        return {r["payload"]["classification_id"]: r["seq"] for r in self.records()}
