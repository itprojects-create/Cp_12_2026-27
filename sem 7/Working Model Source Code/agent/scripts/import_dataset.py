"""Manual import of legitimately acquired datasets (§72).

Hashes the original, validates schema, copies the raw artifact (MANUAL_IMPORT
mode, first-seen now — never backdated), registers provenance + usage, and
normalizes per dataset. Supported: nifty500_membership, announcements,
corporate-actions, filings.

Usage:
  python scripts/import_dataset.py --dataset nifty500_membership --file official_export.csv --source NSE_INDICES_SUBSCRIPTION
  python scripts/import_dataset.py --dataset announcements --file feed.jsonl --source MANUAL_FEED
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.data_acquisition import util as U  # noqa: E402
from app.data import registry as REG  # noqa: E402


def _read_original(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _validate(dataset: str, payload: bytes) -> tuple[bool, str, list[dict]]:
    """Schema validation per dataset. Returns (ok, note, normalized_rows)."""
    if dataset == "nifty500_membership":
        try:
            rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        except Exception as e:  # noqa: BLE001
            return False, f"csv unreadable: {e}", []
        need = {"index_id", "symbol", "valid_from"}
        if not rows or not need <= set(rows[0].keys()):
            return False, f"membership CSV needs columns {sorted(need)}", []
        return True, f"{len(rows)} rows", rows
    if dataset == "announcements":
        rows, bad = [], 0
        for line in payload.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(r, dict) or not r.get("title") or not r.get("timestamp"):
                bad += 1
                continue
            rows.append(r)
        if not rows:
            return False, "no valid announcement rows", []
        return True, f"{len(rows)} rows, {bad} bad lines skipped", rows
    if dataset == "corporate-actions":
        try:
            rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        except Exception as e:  # noqa: BLE001
            return False, f"csv unreadable: {e}", []
        if not rows or "ex_date" not in (rows[0].keys() or []):
            return False, "corporate-action CSV needs ex_date column", []
        return True, f"{len(rows)} rows", rows
    if dataset == "filings":
        if payload[:5] not in (b"<?xml", b"<xbrl") and b"<" not in payload[:200]:
            return False, "not an XML/XBRL filing", []
        return True, f"{len(payload)} bytes XML", []
    return False, f"unknown dataset {dataset!r}", []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True,
                    choices=["nifty500_membership", "announcements",
                             "corporate-actions", "filings"])
    ap.add_argument("--file", required=True)
    ap.add_argument("--source", required=True, help="e.g. NSE_INDICES_SUBSCRIPTION")
    a = ap.parse_args()

    raw = _read_original(a.file)
    digest = U.sha256_bytes(raw)
    ok, note, rows = _validate(a.dataset, raw)
    day = __import__("datetime").datetime.now(__import__("datetime").timezone.utc
                                               ).date().isoformat()
    art = B.store_raw("MANUAL", a.dataset, day,
                      os.path.basename(a.file), raw,
                      source_url=f"manual-import:{a.file}:{a.source}",
                      ingestion_mode="MANUAL_IMPORT",
                      collector_version="import-dataset-v1")
    REG.register(a.dataset, "DEVELOPMENT", source=a.source,
                 note=f"manual import {digest[:16]}")
    REG.record_usage(a.dataset, f"manual:{os.path.basename(a.file)}", "manual-import")
    manifest = U.build_manifest(
        batch_id=f"MANUAL-{a.dataset}-{day}", source="MANUAL", dataset=a.dataset,
        collector_version="import-dataset-v1", requested_start="", requested_end="",
        started_at=U.utcnow(), finished_at=U.utcnow(),
        status="SUCCESS" if ok else "VALIDATION_FAILED",
        records_received=len(rows), records_written=0 if not ok else len(rows),
        invalid=0, raw_artifacts=[art["path"]],
        source_failures=[] if ok else [{"status": "VALIDATION_FAILED", "note": note}])
    print(json.dumps({"original_sha256": digest, "valid": ok, "note": note,
                      "artifact": art["path"], "first_seen_live": False,
                      "manifest": manifest}, indent=2))
    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
