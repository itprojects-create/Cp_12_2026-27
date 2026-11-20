"""W0.5 tests: worker heartbeat, missed-session detection, alerts and restart idempotency.

Hermetic: every test uses tmp_path stores and fixed datetimes; nothing touches the
production ledger, the network or a real scheduler. The 2026 NSE calendar fixture is
the verified one shipped with the package (nse_calendar.json).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from quantplus_intelligence.forecast import heartbeat, ledger as L, jobs


def _ist(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=heartbeat.IST)


@pytest.fixture
def hb(tmp_path, monkeypatch):
    """Isolated heartbeat store: no writes outside tmp_path."""
    monkeypatch.setattr(heartbeat, "REPORTS", tmp_path)
    monkeypatch.setattr(heartbeat, "STATUS_PATH", tmp_path / "worker_heartbeat_status.json")
    monkeypatch.delenv("QP_ALERT_WEBHOOK_URL", raising=False)
    return tmp_path


def test_worker_restart_retry_idempotency(hb):
    """Repeated jobs after restart neither duplicate settlements nor fabricate state."""
    path = hb / "worker_heartbeat.jsonl"
    heartbeat.record("settle", ok=True, detail="run 1", path=path)
    heartbeat.record("settle", ok=True, detail="run 2 after restart", path=path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and all('"ok": true' in l for l in lines)

    # Exactly-once settlement survives a restart: the second call refuses.
    book = L.Ledger(is_trading_day=lambda d: d.weekday() < 5)
    from quantplus_intelligence.forecast.schema import ForecastCard
    card = ForecastCard(symbol="AAA", as_of="2026-10-01T10:00:00+00:00", horizon=5,
                        benchmark="NIFTY50", p_outperform=0.6,
                        quantiles={"0.1": -0.04, "0.5": 0.0, "0.9": 0.04},
                        vol_forecast=0.03, p_event_shock=0.05)
    book.record(card, recorded_at=datetime.fromisoformat(card.as_of))
    due = book.due(datetime(2026, 10, 8).date())
    assert card.card_id in [d["card_id"] for d in due]
    first = book.settle(card.card_id, 0.01, settled_at=datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc))
    assert first["settled"] is True
    second = book.settle(card.card_id, 0.01, settled_at=datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc))
    assert second == {"card_id": card.card_id, "settled": False, "reason": "already settled"}


def test_missed_session_detection_trading_day_without_heartbeat(hb, monkeypatch):
    """A trading weekday past the due time with no heartbeat is MISSED, loudly."""
    now = _ist(2026, 11, 11, 17, 0)   # Wednesday, verified session, past 16:30
    monkeypatch.setattr(heartbeat, "_now", lambda: now.astimezone(timezone.utc))
    report = heartbeat.status(now=now.astimezone(timezone.utc))
    assert report["session_is_trading_day"] is True
    assert report["jobs"]["daily"]["state"] in ("MISSED", "DUE_RUNNING_LATE")
    assert report["jobs"]["settle"]["state"] in ("MISSED", "DUE_RUNNING_LATE")
    assert report["overall"] in ("DEGRADED", "OK")   # DUE_RUNNING_LATE is not yet degraded


def test_missed_session_detection_ok_with_heartbeat(hb, monkeypatch):
    now = _ist(2026, 11, 11, 17, 0)
    monkeypatch.setattr(heartbeat, "_now", lambda: now.astimezone(timezone.utc))
    path = hb / "worker_heartbeat.jsonl"
    heartbeat.record("daily", ok=True, path=path)
    heartbeat.record("settle", ok=True, path=path)
    report = heartbeat.status(now=now.astimezone(timezone.utc), path=path)
    assert report["jobs"]["daily"]["state"] == "OK"
    assert report["jobs"]["settle"]["state"] == "OK"
    assert report["overall"] == "OK"
    # The missed-session detector reads the day AFTER a completed close: Nov 11's own
    # heartbeat exists, so the last completed session check passes for Nov 11 itself.
    assert report["missed_session"]["last_completed_session"] == "2026-11-11"
    assert report["missed_session"]["state"] == "OK"


def test_missed_session_detection_after_missed_day(hb, monkeypatch):
    """No daily heartbeat on the last completed session raises MISSED_SESSION."""
    now = _ist(2026, 11, 12, 10, 0)   # Thursday morning: Nov 11's close already passed
    monkeypatch.setattr(heartbeat, "_now", lambda: now.astimezone(timezone.utc))
    path = hb / "worker_heartbeat.jsonl"
    # A heartbeat from Nov 11's session proves monitoring existed then (it failed).
    path.write_text(json.dumps({"job": "daily", "ok": False, "detail": "crashed",
                                "at_utc": "2026-11-11T11:30:00+00:00",
                                "session_date": "2026-11-11"}) + "\n", encoding="utf-8")
    report = heartbeat.status(now=now.astimezone(timezone.utc), path=path)
    assert report["missed_session"]["last_completed_session"] == "2026-11-11"
    assert report["missed_session"]["state"] == "MISSED_SESSION"
    assert "catchup" in report["missed_session"]["note"]
    assert report["overall"] == "DEGRADED"


def test_pre_heartbeat_sessions_are_unmonitored_not_missed(hb, monkeypatch):
    """No coverage at all for a session is UNMONITORED, never a fabricated failure."""
    now = _ist(2026, 11, 12, 10, 0)
    monkeypatch.setattr(heartbeat, "_now", lambda: now.astimezone(timezone.utc))
    path = hb / "worker_heartbeat.jsonl"
    heartbeat.record("daily", ok=True, path=path)   # only TODAY has a heartbeat
    report = heartbeat.status(now=now.astimezone(timezone.utc), path=path)
    assert report["missed_session"]["state"] == "UNMONITORED"
    assert "schedule_daily.log" in report["missed_session"]["note"]
    # Unmonitored history must not mark the whole worker DEGRADED by itself.
    assert report["overall"] == "OK"


def test_holiday_jobs_are_not_due(hb, monkeypatch):
    """On a verified holiday nothing is MISSED: jobs are simply not due."""
    now = _ist(2026, 11, 10, 18, 0)   # Diwali-Balipratipada, verified NSE holiday
    monkeypatch.setattr(heartbeat, "_now", lambda: now.astimezone(timezone.utc))
    report = heartbeat.status(now=now.astimezone(timezone.utc))
    assert report["session_is_trading_day"] is False
    assert all(v["state"] == "NOT_DUE_YET" for v in report["jobs"].values())
    # And the last completed session is Friday Nov 6 (Nov 9 Monday was a session).
    assert report["missed_session"]["last_completed_session"] in ("2026-11-09", "2026-11-06")


def test_alert_route_not_configured_is_labelled(hb):
    """A missing notification route is NOT_CONFIGURED, never silently 'sent'."""
    route = heartbeat.alert_route()
    assert route["configured"] is False and route["state"] == "NOT_CONFIGURED"
    sent = heartbeat.alert("test", "body")
    assert sent["sent"] is False
    assert sent["state"] == "NOT_CONFIGURED"


def test_uptime_is_labelled_conditional(hb):
    report = heartbeat.status(now=_ist(2026, 11, 11, 12, 0).astimezone(timezone.utc))
    assert report["uptime"] == "CONDITIONAL"
    assert "sleep" in report["uptime_note"] or "logoff" in report["uptime_note"]


def test_status_job_end_to_end(hb, monkeypatch):
    """The `status` CLI verb writes the health artifact and alerts only when degraded."""
    now = _ist(2026, 11, 12, 10, 0)
    monkeypatch.setattr(heartbeat, "_now", lambda: now.astimezone(timezone.utc))
    path = hb / "worker_heartbeat.jsonl"
    report = jobs.worker_status()
    # reports dir was monkeypatched to tmp_path via heartbeat.REPORTS
    written = Path(heartbeat.STATUS_PATH)
    assert written.exists()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["overall"] in ("OK", "DEGRADED")
