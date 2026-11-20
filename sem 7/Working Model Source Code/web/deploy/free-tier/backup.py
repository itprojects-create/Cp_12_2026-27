"""Consistent SQLite snapshots, without copying live WAL files. Python stdlib only."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

DATABASES = (
    "quantplus.db", "forecast_ledger.sqlite3",
    "news_archive.sqlite3", "sentiment_history.sqlite3",
)


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Snapshot destination must be outside the source directory")
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "databases": {}}
    for name in DATABASES:
        original = source / name
        if not original.is_file():
            raise FileNotFoundError(f"Required database missing: {name}")
        target = destination / name
        # mode=ro refuses accidental creation and includes committed WAL contents.
        with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=256, sleep=0.1)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError(f"SQLite integrity failed: {name}")
                if name == "forecast_ledger.sqlite3":
                    previous, count = "0" * 64, 0
                    for seq, card, payload, stamp, prev, digest in dst.execute(
                        "SELECT seq, card_id, payload, recorded_at, prev_hash, hash "
                        "FROM forecast_ledger ORDER BY seq"
                    ):
                        actual = hashlib.sha256(f"{previous}|{card}|{payload}|{stamp}".encode()).hexdigest()
                        if previous != prev or actual != digest:
                            raise ValueError(f"Forecast chain broken at {seq}")
                        previous, count = digest, count + 1
                    manifest["forecast_chain"] = {"valid": True, "checked": count, "head": previous}
        manifest["databases"][name] = {"bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    (destination / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"databases": len(manifest["databases"]),
        "forecast_chain": manifest.get("forecast_chain"), "destination": str(destination)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    snapshot(args.source, args.destination)
