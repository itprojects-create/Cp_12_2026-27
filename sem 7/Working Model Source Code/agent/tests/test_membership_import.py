"""Phase H membership/importer tests. Hermetic."""
from __future__ import annotations

import json

import pytest

from app.data import membership_recon as RECON
from app.data import pit_membership as PM
from app.db import sqlite_conn


def _clean():
    PM.clear_cache()
    RECON.init_tables()
    sqlite_conn().execute("DELETE FROM membership_recon WHERE recon_id LIKE 'RECON-%'")
    sqlite_conn().commit()


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def test_recon_partial_intervals_and_leakage_shape():
    r = RECON.record("nifty50", "2026-09-01", "2026-09-30", ["NEWCO"], ["OLDCO"],
                     "NSE press release PR-123")
    assert r["recon_id"].startswith("RECON-")
    r2 = RECON.record("nifty50", "2026-09-01", "2026-09-30", ["NEWCO"], ["OLDCO"],
                      "NSE press release PR-123")
    assert r2["recon_id"] == r["recon_id"]  # content-idempotent
    ivs = RECON.to_intervals("nifty50")
    assert len(ivs) == 1 and ivs[0].instrument_id == "NEWCO.NS"
    assert ivs[0].pit_confidence == "PARTIAL"
    assert ivs[0].source_class == "PRESS_RELEASE_RECONSTRUCTION"
    with pytest.raises(ValueError):
        RECON.record("nifty50", "2026-09-30", "2026-09-01", ["X"], [], "doc")


def test_source_classes_never_equivalent():
    assert PM.MembershipInterval(
        instrument_id="A.NS", universe_id="nifty50", effective_from="2020-01-01",
        source="press_release", source_hash="h").source_class == \
        "PRESS_RELEASE_RECONSTRUCTION"
    snap = PM.membership_at("nifty50", "2026-10-01", strict=False)
    assert snap["source_class"] == "PRESS_RELEASE_RECONSTRUCTION"


def test_manual_import_validates_and_hashes(tmp_path):
    import subprocess
    good = tmp_path / "mem.csv"
    good.write_text("index_id,symbol,valid_from,valid_to,source\n217,FOO,2020-01-01,,press_release\n",
                    encoding="utf-8")
    r = subprocess.run(["python", "scripts/import_dataset.py", "--dataset",
                        "nifty500_membership", "--file", str(good),
                        "--source", "TEST-SUB"],
                       capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["valid"] is True and len(out["original_sha256"]) == 64
    assert out["first_seen_live"] is False
    bad = tmp_path / "bad.csv"
    bad.write_text("nope\n", encoding="utf-8")
    r2 = subprocess.run(["python", "scripts/import_dataset.py", "--dataset",
                         "nifty500_membership", "--file", str(bad),
                         "--source", "TEST-SUB"],
                        capture_output=True, text=True, cwd=".")
    assert r2.returncode == 2
    assert json.loads(r2.stdout)["valid"] is False
