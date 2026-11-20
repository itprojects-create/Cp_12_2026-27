"""P2 backup/snapshot tests (§84). Hermetic temp dirs + temp DB."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
import backup_evidence as BE  # noqa: E402
from app.data_acquisition import snapshots as SNAP  # noqa: E402


def test_snapshot_create_validate_and_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(SNAP, "SNAP_DIR", str(tmp_path / "snaps"))
    rec = SNAP.create_snapshot("SNAP-T1", [{"name": "d"}], [{"hash": "ab"}], [])
    assert os.path.exists(rec["path"])
    v = SNAP.validate_snapshot("SNAP-T1")
    # fixture hash unresolvable in this ledger: INVALID, stated not hidden
    assert v["valid"] is False
    assert any("unresolvable" in f for f in v["failures"])
    assert SNAP.validate_snapshot("SNAP-MISSING")["valid"] is False
    import pytest
    with pytest.raises(ValueError):
        SNAP.create_snapshot("SNAP-T1", [], [], [])


def test_backup_restore_roundtrip_and_corruption(tmp_path):
    dest = str(tmp_path / "backups")
    rec = BE.run_backup(dest, day="2026-10-10")
    assert os.path.exists(os.path.join(rec["backup"], "backup_manifest.json"))
    rep = BE.restore_rehearsal(rec["backup"])
    assert rep["ok"] is True
    # corrupt one restored-source byte -> rehearsal must reject
    man_path = os.path.join(rec["backup"], "backup_manifest.json")
    man = json.load(open(man_path, encoding="utf-8"))
    first_rel = next(iter(man["hashes"]))
    with open(os.path.join(rec["backup"], first_rel), "ab") as f:
        f.write(b"X")
    rep2 = BE.restore_rehearsal(rec["backup"])
    assert rep2["ok"] is False
    assert any("mismatch" in f or "missing" in f for f in rep2["failures"])
    # missing backup dir
    assert BE.restore_rehearsal(str(tmp_path / "nope"))["ok"] is False
