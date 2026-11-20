"""Acquisition framework tests (Phase A). Hermetic — no network."""
from __future__ import annotations

import json
import os

import pytest

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import scheduler as SCH
from app.data_acquisition import util as U
from app.db import sqlite_conn


@pytest.fixture(autouse=True)
def _clean():
    B.init_tables()
    yield
    db = sqlite_conn()
    db.execute("DELETE FROM acquisition_errors WHERE source LIKE 'TEST-%'")
    db.execute("DELETE FROM source_health WHERE source LIKE 'TEST-%'")
    db.execute("DELETE FROM backfill_state WHERE dataset LIKE 'TEST-%'")
    db.execute("DELETE FROM acquisition_ledger WHERE source LIKE 'TEST-%'")
    db.commit()


def test_status_enum_covers_contract():
    assert {s.value for s in B.FetchStatus} >= {
        "SUCCESS", "PARTIAL", "SOURCE_UNAVAILABLE", "SOURCE_SCHEMA_CHANGED",
        "RATE_LIMITED", "AUTH_REQUIRED", "SUBSCRIPTION_REQUIRED", "NO_DATA",
        "VALIDATION_FAILED", "SOURCE_BLOCKED"}


def test_manifest_hash_stable_and_content_bound():
    m1 = U.build_manifest(batch_id="b", source="s", dataset="d", started_at="t",
                          finished_at="t2")
    m2 = U.build_manifest(batch_id="b", source="s", dataset="d", started_at="t",
                          finished_at="t2")
    assert m1["manifest_hash"] == m2["manifest_hash"] and len(m1["manifest_hash"]) == 16
    for k in ("batch_id", "status", "records_received", "raw_artifacts",
              "source_failures", "manifest_hash"):
        assert k in m1


def test_content_address_dedup_and_first_seen_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path))
    a1 = B.store_raw("TEST-SRC", "ds", "2026-10-10", "f.csv", b"bytes-1",
                     ingestion_mode="BACKFILL")
    a2 = B.store_raw("TEST-SRC", "ds", "2026-10-10", "f.csv", b"bytes-1",
                     ingestion_mode="BACKFILL")
    assert a1["sha256"] == a2["sha256"]
    assert a2["duplicate_payload"] is True and a1["duplicate_payload"] is False
    assert a1["path"] == a2["path"]  # payload written once
    assert os.path.exists(a1["path"] + ".meta.json")
    rows = sqlite_conn().execute(
        "SELECT n_observations, first_seen_ts FROM acquisition_ledger"
        " WHERE artifact_hash=?", (a1["sha256"],)).fetchall()
    assert len(rows) == 1 and rows[0][0] == 2  # re-observation counted, single row
    first = rows[0][1]
    a3 = B.store_raw("TEST-SRC", "ds", "2026-10-11", "f.csv", b"bytes-1")
    assert sqlite_conn().execute(
        "SELECT first_seen_ts FROM acquisition_ledger WHERE artifact_hash=?",
        (a1["sha256"],)).fetchone()[0] == first  # never backdated (§90)


def test_error_log_and_health_lifecycle():
    B.log_error("TEST-S", "ds", "2026-10-10", "SOURCE_UNAVAILABLE", "down")
    B.log_error("TEST-S", "ds", "2026-10-10", "SOURCE_UNAVAILABLE", "down")
    snap = {f"{h['source']}/{h['dataset']}": h for h in B.health_snapshot()}
    assert snap["TEST-S/ds"]["consecutive_failures"] == 2
    assert snap["TEST-S/ds"]["status"] == "DEGRADED"
    for _ in range(4):
        B.log_error("TEST-S", "ds", "2026-10-10", "SOURCE_UNAVAILABLE", "down")
    snap = {f"{h['source']}/{h['dataset']}": h for h in B.health_snapshot()}
    assert snap["TEST-S/ds"]["status"] == "DOWN"
    B.mark_health("TEST-S", "ds", ok=True)
    snap = {f"{h['source']}/{h['dataset']}": h for h in B.health_snapshot()}
    assert snap["TEST-S/ds"]["status"] == "HEALTHY"
    assert snap["TEST-S/ds"]["consecutive_failures"] == 0


def test_checkpoint_resume_never_restarts():
    assert B.checkpoint_get("TEST-DS") is None
    B.checkpoint_set("TEST-DS", "2024-01-05", "2024-01-06")
    B.checkpoint_set("TEST-DS", "2024-01-05", "2024-01-06", failed=True, failure_note="x")
    cp = B.checkpoint_get("TEST-DS")
    assert cp["next_window"] == "2024-01-06" and cp["failure_count"] == 1


def test_retry_bounds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("x")
        return "ok"

    assert U.with_retries(flaky, retries=3, what="t") == "ok"
    assert calls["n"] == 3
    with pytest.raises(ValueError):
        U.with_retries(flaky, retries=99)
    with pytest.raises(ValueError):
        H.get("http://x", retries=99)


def test_http_pacing_and_retry_after(monkeypatch):
    import urllib.request
    seen = {"n": 0}

    class _Resp:
        status = 429
        headers = {"Retry-After": "0"}

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["n"] += 1
        if seen["n"] < 3:
            return _Resp()
        raise OSError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(H.time, "sleep", lambda s: None)
    with pytest.raises(H.HttpError):
        H.get("http://test-host/x", retries=1, min_interval_s=0)
    assert seen["n"] == 2  # bounded: initial + 1 retry


def test_scheduler_windows_and_jobs():
    assert {"INTRADAY_EVENTS", "POST_CLOSE_MARKET", "POST_SETTLEMENT",
            "WEEKLY_RECONCILIATION"} <= set(SCH.WINDOWS)
    assert "daily_market" in SCH.JOBS and "announcements" in SCH.JOBS
    text = SCH.instructions()
    assert "cron" in text and "schtasks" in text


def test_quality_report_never_repairs():
    q = U.quality_report(100, 90, invalid=5, duplicates=2, pit_verified=80,
                         pit_partial=5, pit_unknown=5)
    assert q["coverage"] == 0.9 and q["invalid_record_rate"] == round(5 / 90, 4)
    assert q["pit_verified_pct"] == round(100 * 80 / 90, 2)
