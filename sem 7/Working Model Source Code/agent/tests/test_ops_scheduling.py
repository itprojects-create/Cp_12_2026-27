"""P0 scheduling tests (§82). Hermetic (fixture holiday file, temp DB)."""
from __future__ import annotations

import json

from app.data_acquisition import scheduler as SCH
from app.ops import calendar as CAL
from app.ops import log as OPS
from app.db import sqlite_conn


def test_calendar_kinds():
    hol = {"2026-10-02": {"kind": "HOLIDAY", "note": "Gandhi Jayanti"},
           "2026-11-08": {"kind": "SPECIAL_MUHURAT", "note": "Diwali"}}
    assert CAL.session_kind("2026-10-10", hol) == "WEEKEND"  # Saturday
    assert CAL.session_kind("2026-10-12", hol) == "NORMAL"  # Monday
    assert CAL.session_kind("2026-10-02", hol) == "HOLIDAY"
    assert CAL.session_kind("2026-11-08", hol) == "SPECIAL_MUHURAT"
    assert CAL.is_trading_day("2026-11-08", hol) is True  # Muhurat publishes
    assert CAL.is_trading_day("2026-10-10", hol) is False
    assert CAL.expected_eod("2026-10-12", hol) is True
    assert CAL.load_holidays("/nope/missing.json") == {}  # missing file, no crash


def test_missed_run_detection():
    OPS.init_tables()
    sqlite_conn().execute("DELETE FROM job_runs WHERE job LIKE 'TEST-%'")
    sqlite_conn().commit()
    assert OPS.check_gaps(["TEST-JOB"], "2026-10-10T12:00:00+00:00", 24) == [
        {"job": "TEST-JOB", "gap": "NEVER_RUN"}]
    OPS.log("TEST-JOB", "finish", status="OK")
    assert OPS.check_gaps(["TEST-JOB"], "2026-10-10T12:00:00+00:00", 24 * 365) == []
    OPS.log("TEST-JOB", "fail", status="FAIL")
    gaps = OPS.check_gaps(["TEST-JOB"], "2026-10-10T12:00:00+00:00", 24 * 365)
    assert gaps and gaps[0]["gap"] == "EXPECTED_RUN_MISSING"
    sqlite_conn().execute("DELETE FROM job_runs WHERE job LIKE 'TEST-%'")
    sqlite_conn().execute("DELETE FROM operations_log WHERE job LIKE 'TEST-%'")
    sqlite_conn().commit()


def test_post_close_dry_run_weekend_and_duplicate_invocation(tmp_path):
    from scripts import run_post_close as RPC
    sat = RPC.run_post_close("2026-10-10", dry_run=True)  # Saturday
    assert sat["session"] == "WEEKEND"
    assert sat["steps"]["equity-eod"]["status"] in ("DRY_RUN", "SKIPPED")
    mon = RPC.run_post_close("2026-10-12", dry_run=True)
    assert mon["session"] == "NORMAL"
    again = RPC.run_post_close("2026-10-12", dry_run=True)
    assert again == mon  # dry runs deterministic; live reruns idempotent by hashes


def test_restart_after_crash_uses_checkpoints():
    from app.data_acquisition import base as B
    B.init_tables()
    B.checkpoint_set("TEST-DS", "2024-01-05", "2024-01-06", failed=True,
                     failure_note="crash")
    cp = B.checkpoint_get("TEST-DS")
    assert cp["next_window"] == "2024-01-06" and cp["failure_count"] == 1
    sqlite_conn().execute("DELETE FROM backfill_state WHERE dataset='TEST-DS'")
    sqlite_conn().commit()


def test_job_registry_covers_classes():
    assert {"INTRADAY_EVENTS", "POST_CLOSE_MARKET", "POST_SETTLEMENT", "WEEKLY_FORWARD",
            "WEEKLY_RECONCILIATION", "DAILY_HEALTH", "DAILY_SNAPSHOT", "BACKUP",
            "MONTHLY_AUDIT"} <= set(SCH.WINDOWS)
    assert {"daily_market", "weekly_forward", "backup", "monthly_audit"} <= set(SCH.JOBS)
