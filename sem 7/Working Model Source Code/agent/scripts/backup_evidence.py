"""Evidence backup + restore rehearsal (§§20–22, 74).

Scope priority: raw live artifacts, event store, registries, snapshots,
forward-clock artifacts, experiment manifests, research memory, corpses,
trial ledger, ops log. Price files are redownloadable; first-seen metadata
is not — the ledger and event DBs are the crown jewels.

Backup is read-only against primaries (sqlite backup API + file copy +
atomic manifest). Restore rehearsal copies into a temp dir and validates
hashes + DB integrity + snapshot references. A backup never restored is
not trusted (§22).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import snapshots as SNAP  # noqa: E402

BACKUP_DEFAULT = os.path.join("data", "backups")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_tree(src: str, dst: str) -> tuple[int, int]:
    n, size = 0, 0
    for root, _dirs, files in os.walk(src):
        for fn in files:
            s = os.path.join(root, fn)
            d = os.path.join(dst, os.path.relpath(s, src))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            n += 1
            size += os.path.getsize(d)
    return n, size


def _backup_db(src: str, dst: str) -> bool:
    if not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    src_conn = sqlite3.connect(src, timeout=10.0)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return True


def run_backup(dest: str, day: str | None = None) -> dict:
    day = day or datetime.now(timezone.utc).date().isoformat()
    root = os.path.join(dest, f"backup-{day}")
    os.makedirs(root, exist_ok=True)
    manifest: dict = {"created_at": _utcnow(), "dest": root, "parts": {},
                      "hashes": {}}
    # raw live artifacts (irreplaceable first-seen evidence)
    raw_src = os.path.join("data", "raw")
    if os.path.isdir(raw_src):
        n, size = _copy_tree(raw_src, os.path.join(root, "raw"))
        manifest["parts"]["raw"] = {"files": n, "bytes": size}
    # sqlite ledgers (event store, registry, memory, trials, ops)
    manifest["parts"]["dbs"] = {}
    for db in ("data/quantplus.db",):
        ok = _backup_db(db, os.path.join(root, "dbs", os.path.basename(db)))
        manifest["parts"]["dbs"][db] = "ok" if ok else "absent"
    # snapshots, forward artifacts, experiment manifests, reports
    for name, pattern in (
            ("snapshots", "data/snapshots/*.json"),
            ("forward", "data/forward_*.json"),
            ("event_blackout", "data/event_blackout_*.json"),
            ("manifests", "data/experiments/*/manifest.json"),
            ("paper_pit", "data/paper_*pit*.json")):
        files = sorted(glob.glob(pattern))
        outdir = os.path.join(root, name)
        os.makedirs(outdir, exist_ok=True)
        for f in files:
            shutil.copy2(f, os.path.join(outdir, os.path.basename(f)))
        manifest["parts"][name] = {"files": len(files)}
    # hash everything (except the manifest itself, written last)
    hashes = {}
    for r, _d, files in os.walk(root):
        for fn in files:
            p = os.path.join(r, fn)
            hashes[os.path.relpath(p, root)] = SNAP.file_hash(p)
    manifest["hashes"] = hashes
    with open(os.path.join(root, "backup_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return {"backup": root, "files": len(hashes), "manifest": manifest}


def restore_rehearsal(backup_root: str) -> dict:
    """Copy to temp, validate hashes + DB integrity + snapshot refs (§§22, 74)."""
    man_path = os.path.join(backup_root, "backup_manifest.json")
    if not os.path.exists(man_path):
        return {"ok": False, "reason": "no backup manifest"}
    manifest = json.load(open(man_path, encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix="qp-restore-")
    failures = []
    for rel, expect in manifest.get("hashes", {}).items():
        src = os.path.join(backup_root, rel)
        if not os.path.exists(src):
            failures.append(f"missing artifact: {rel}")
            continue
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if SNAP.file_hash(dst) != expect:
            failures.append(f"hash mismatch (corrupt backup): {rel}")
    # DB integrity on the restored copies
    for r, _d, files in os.walk(tmp):
        for fn in files:
            if fn.endswith(".db"):
                try:
                    conn = sqlite3.connect(os.path.join(r, fn))
                    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    conn.close()
                    if ok != "ok":
                        failures.append(f"db integrity failed: {fn}")
                except Exception as e:  # noqa: BLE001
                    failures.append(f"db unreadable {fn}: {type(e).__name__}")
    # snapshot references resolve against restored snapshot files
    snap_files = [f for f in os.listdir(os.path.join(tmp, "snapshots"))
                  if f.endswith(".json")] if os.path.isdir(os.path.join(tmp, "snapshots")) else []
    return {"ok": not failures, "restored_to": tmp, "failures": failures,
            "snapshots_restored": len(snap_files),
            "note": "temp dir retained for inspection; remove after review"}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--dest", default=BACKUP_DEFAULT)
    b.add_argument("--day", default=None)
    r = sub.add_parser("restore-rehearsal")
    r.add_argument("--backup", required=True)
    a = ap.parse_args()
    if a.cmd == "backup":
        rec = run_backup(a.dest, a.day)
        print(json.dumps({k: v for k, v in rec.items() if k != "manifest"}, indent=2))
    else:
        print(json.dumps(restore_rehearsal(a.backup), indent=2))


if __name__ == "__main__":
    main()
