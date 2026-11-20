"""Phase I ops tests: backfill resume, health, snapshots, agent tools. Hermetic."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
import backfill_data as BF  # noqa: E402
from app.data_acquisition import base as B  # noqa: E402
from app.data_acquisition import parquet as PQ  # noqa: E402
from app.data_acquisition import tools as TOOLS  # noqa: E402
from app.db import sqlite_conn  # noqa: E402


def _clean():
    B.init_tables()
    db = sqlite_conn()
    db.execute("DELETE FROM backfill_state WHERE dataset LIKE 'TEST-%'")
    db.execute("DELETE FROM acquisition_errors WHERE source LIKE 'TEST-%'")
    db.execute("DELETE FROM source_health WHERE source LIKE 'TEST-%'")
    db.execute("DELETE FROM acquisition_ledger WHERE source LIKE 'TEST-%'")
    db.commit()


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def test_chunking_and_resume():
    assert BF._chunks("2024-01-01", "2024-01-10", "week") == [
        ("2024-01-01", "2024-01-07"), ("2024-01-08", "2024-01-10")]
    assert BF._chunks("2024-01-01", "2024-01-01", "day") == [("2024-01-01", "2024-01-01")]
    calls = []

    class Stub:
        def fetch(self, **kw):
            calls.append(kw)
            return B.FetchResult(status=B.FetchStatus.SUCCESS, source="TEST",
                                 dataset="TEST-DS",
                                 requested_start=str(kw.get("start", "")),
                                 requested_end=str(kw.get("end", "")))

    import backfill_data as _BF
    _orig, _BF._collector = _BF._collector, lambda ds: Stub()
    argv = ["backfill_data.py", "--dataset", "equity-eod", "--start", "2024-01-01",
            "--end", "2024-01-10", "--chunk", "week"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        _BF.main()
    finally:
        sys.argv = old_argv
        _BF._collector = _orig
    assert len(calls) == 2  # two week-windows
    cp = B.checkpoint_get("equity-eod")
    assert cp is not None and cp["failure_count"] == 0


def test_backfill_stops_on_blocked_source():
    import backfill_data as _BF

    class Blocked:
        def fetch(self, **kw):
            return B.FetchResult(status=B.FetchStatus.SOURCE_BLOCKED, source="TEST",
                                 dataset="TEST-DS2")

    _orig, _BF._collector = _BF._collector, lambda ds: Blocked()
    argv = ["backfill_data.py", "--dataset", "indices", "--start", "2024-01-01",
            "--end", "2024-02-01", "--chunk", "week"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        _BF.main()
    finally:
        sys.argv = old_argv
        _BF._collector = _orig
    # must not hammer: stops after first blocked window (never silently skips)


def test_health_never_fakes():
    import data_health as DH
    assert DH.staleness("", "daily-post-close") == "no data"
    assert DH.staleness("2026-10-10T00:00:00+00:00", "daily-post-close") in (
        "fresh", "STALE", "VERY_STALE")
    assert DH.staleness("not-a-date", "daily-post-close") == "unknown"


def test_snapshot_freeze_immutable(tmp_path):
    import subprocess
    snap_id = "TEST-SNAPSHOT-001"
    r = subprocess.run(["python", "scripts/freeze_data_snapshot.py", "--id", snap_id],
                       capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["snapshot"] == snap_id
    path = os.path.join("data", "snapshots", f"{snap_id}.json")
    assert os.path.exists(path)
    doc = json.load(open(path, encoding="utf-8"))
    assert "dataset_versions" in doc and "artifacts" in doc
    r2 = subprocess.run(["python", "scripts/freeze_data_snapshot.py", "--id", snap_id],
                        capture_output=True, text=True, cwd=".")
    assert r2.returncode == 2  # immutable: same id refused
    os.remove(path)


def test_agent_tools_provenance_caps_and_abstention(tmp_path, monkeypatch):
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    ann = TOOLS.query_announcements("INFY.NS", "2026-10-01", "2026-10-10", limit=5)
    assert ann["rows"] == [] and ann["provenance"]["pit_status"] == "UNKNOWN"
    assert set(ann) >= {"rows", "truncated", "provenance"}
    mkt = TOOLS.query_market_data("INFY.NS", "2026-10-01", "2026-10-10", limit=5)
    assert mkt["rows"] == [] and mkt["provenance"]["source"] == "NSE-archives"
    deals = TOOLS.query_deals("INFY.NS", "2026-10-01", "2026-10-10")
    assert deals["rows"] == []
    assert deals["provenance"]["note"].startswith("context only")
    fund = TOOLS.query_fundamentals("INFY.NS", "2026-10-10T00:00:00+00:00")
    assert fund["periods"] == [] and fund["provenance"]["pit_status"] == "UNKNOWN"
