"""Append-only immutable disclosure-version metadata store."""
from __future__ import annotations

import json
from pathlib import Path

from quantplus_intelligence.research_v3.wave5_common import canonical_json, semantic_sha256

from .contracts import CapturedDisclosureVersion


STORE_SCHEMA = "research_v3/event_capture_store/1"
GENESIS = "0" * 64


class EventCaptureStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def by_version_id(self, version_id: str) -> dict | None:
        return next((record for record in self.records()
                     if record["payload"]["version_id"] == version_id), None)

    def versions_for_disclosure(self, disclosure_id: str) -> list[dict]:
        return [record for record in self.records()
                if record["payload"]["disclosure_id"] == disclosure_id]

    def latest_for_provider_document(self, source_id: str,
                                     provider_document_id: str) -> dict | None:
        rows = [record for record in self.records()
                if record["payload"]["source_id"] == source_id
                and record["payload"]["provider_document_id"] == provider_document_id]
        return rows[-1] if rows else None

    def append(self, version: CapturedDisclosureVersion) -> tuple[dict, bool]:
        current = self.records()
        if current:
            intact, reason = self.verify_chain()
            if not intact:
                raise RuntimeError("refusing append to invalid capture chain: " + reason)
        existing = self.by_version_id(version.version_id)
        if existing:
            return existing, False
        records = current
        seq = len(records) + 1
        prev_hash = records[-1]["record_hash"] if records else GENESIS
        payload = version.to_payload()
        record = {
            "store_schema": STORE_SCHEMA,
            "seq": seq,
            "prev_hash": prev_hash,
            "payload": payload,
        }
        record["record_hash"] = semantic_sha256({
            "seq": seq, "prev_hash": prev_hash, "payload": payload,
        })
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(record) + "\n")
        return record, True

    def verify_chain(self) -> tuple[bool, str]:
        prev = GENESIS
        for seq, record in enumerate(self.records(), start=1):
            expected = semantic_sha256({
                "seq": seq, "prev_hash": prev, "payload": record["payload"],
            })
            if record.get("seq") != seq:
                return False, f"seq {seq}: sequence mismatch"
            if record.get("prev_hash") != prev:
                return False, f"seq {seq}: prev_hash mismatch"
            if record.get("record_hash") != expected:
                return False, f"seq {seq}: record_hash mismatch"
            prev = expected
        return True, "chain intact"

    def health(self) -> dict:
        records = self.records()
        ok, reason = self.verify_chain()
        return {
            "store_schema": STORE_SCHEMA,
            "versions": len(records),
            "unique_disclosures": len({row["payload"]["disclosure_id"] for row in records}),
            "contemporaneous_versions": sum(
                row["payload"]["pit_class"] == "CONTEMPORANEOUS" for row in records),
            "retrospective_versions": sum(
                row["payload"]["pit_class"] == "RETROSPECTIVE_RETRIEVAL"
                for row in records),
            "chain_intact": ok,
            "chain_reason": reason,
            "head_hash": records[-1]["record_hash"] if records else GENESIS,
        }
