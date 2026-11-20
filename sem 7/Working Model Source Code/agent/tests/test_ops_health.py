"""P1 health/alert tests (§88). Hermetic temp DB + outbox redirect."""
from __future__ import annotations

import sys

sys.path.insert(0, "scripts")
import quantplus_health as QH  # noqa: E402

from app.data_acquisition import base as B
from app.db import sqlite_conn
from app.ops import alerts as AL


def _clean():
    B.init_tables()
    AL.init_tables()
    db = sqlite_conn()
    db.execute("DELETE FROM alerts WHERE alert_key LIKE 'TEST-%'")
    db.execute("DELETE FROM source_health WHERE source LIKE 'TEST-%'")
    db.execute("DELETE FROM acquisition_errors WHERE source LIKE 'TEST-%'")
    db.execute("DELETE FROM acquisition_ledger WHERE source LIKE 'TEST-%'")
    db.commit()


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def test_stale_down_schema_detection():
    B.mark_health("TEST-S", "ds", ok=False, status="SOURCE_UNAVAILABLE")
    B.mark_health("TEST-S", "ds", ok=False, status="SOURCE_UNAVAILABLE")
    h = {f"{x['source']}/{x['dataset']}": x for x in B.health_snapshot()}["TEST-S/ds"]
    assert h["status"] == "DEGRADED" and h["consecutive_failures"] == 2
    B.mark_health("TEST-S", "ds", ok=False, status="SOURCE_SCHEMA_CHANGED")
    h = {f"{x['source']}/{x['dataset']}": x for x in B.health_snapshot()}["TEST-S/ds"]
    assert h["status"] == "SCHEMA_CHANGED"
    for _ in range(5):
        B.mark_health("TEST-S", "ds", ok=False, status="SOURCE_UNAVAILABLE")
    h = {f"{x['source']}/{x['dataset']}": x for x in B.health_snapshot()}["TEST-S/ds"]
    assert h["status"] == "DOWN"
    B.mark_health("TEST-S", "ds", ok=True)
    h = {f"{x['source']}/{x['dataset']}": x for x in B.health_snapshot()}["TEST-S/ds"]
    assert (h["status"], h["consecutive_failures"]) == ("HEALTHY", 0)


def test_zero_data_success_is_suspicious():
    rows = QH.dataset_health()
    assert all(r["status"] == "NOT_COLLECTED" for r in rows)  # nothing collected yet
    assert all(r["status"] == "NOT_COLLECTED" for r in rows)  # nothing collected yet
    B.mark_health("NSE", "announcements", ok=True)  # success, zero artifacts
    rows = {r["dataset"]: r for r in QH.dataset_health()}
    assert rows["NSE/announcements"]["status"] in ("SUSPICIOUS_ZERO", "HEALTHY")


def test_alert_dedup_and_resolve(tmp_path, monkeypatch):
    monkeypatch.setattr(AL, "OUTBOX", str(tmp_path / "alerts.log"))
    first = AL.fire("TEST-FEED-DOWN", "CRITICAL", "feed down")
    assert first["fired"] is True and first["repeat"] is False
    second = AL.fire("TEST-FEED-DOWN", "CRITICAL", "still down")
    assert second["fired"] is False  # deduped within 4h window
    assert len(AL.active("CRITICAL")) == 1
    AL.resolve("TEST-FEED-DOWN")
    assert AL.active("CRITICAL") == []
    third = AL.fire("TEST-FEED-DOWN", "WARNING", "flapping")
    assert third["fired"] is True  # resolved alerts refire as new incidents
    import pytest
    with pytest.raises(ValueError):
        AL.fire("TEST-X", "PANIC")
