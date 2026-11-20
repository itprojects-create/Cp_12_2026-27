"""Dataset snapshot freezer (§77): manifest of versions/hashes/coverage/PIT/health.

Experiments reference the snapshot ID instead of hoping today's files match.
Snapshots are immutable once written (same id + different content -> error).

Usage: python scripts/freeze_data_snapshot.py [--id SNAP-20261010] [--datasets equity-eod,indices]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import registry as REG  # noqa: E402
from app.data_acquisition import base as B  # noqa: E402
from app.db import sqlite_conn  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default=None)
    ap.add_argument("--datasets", default="")
    a = ap.parse_args()
    REG.init_tables()
    B.init_tables()
    REG.seed_known()
    snap_id = a.id or f"SNAP-{datetime.now(timezone.utc).date().isoformat()}"
    path = os.path.join("data", "snapshots", f"{snap_id}.json")
    if os.path.exists(path):
        print(json.dumps({"snapshot": snap_id, "error": "immutable: id exists"}))
        sys.exit(2)
    wanted = [d.strip() for d in a.datasets.split(",") if d.strip()]
    datasets = REG.list_datasets()
    if wanted:
        datasets = [d for d in datasets if d["name"] in wanted]
    artifacts = sqlite_conn().execute(
        "SELECT artifact_hash, source, dataset, ingestion_mode, first_seen_ts,"
        " publication_ts, bytes FROM acquisition_ledger ORDER BY artifact_hash"
    ).fetchall()
    doc = {"snapshot_id": snap_id,
           "created_at": datetime.now(timezone.utc).isoformat(),
           "dataset_versions": datasets,
           "artifacts": [{"hash": r[0], "source": r[1], "dataset": r[2],
                          "ingestion_mode": r[3], "first_seen_ts": r[4],
                          "publication_ts": r[5], "bytes": r[6]} for r in artifacts],
           "source_health": B.health_snapshot()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    print(json.dumps({"snapshot": snap_id, "datasets": len(datasets),
                      "artifacts": len(artifacts), "path": path}, indent=2))


if __name__ == "__main__":
    main()
