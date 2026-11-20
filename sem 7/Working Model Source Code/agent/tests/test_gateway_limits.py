"""Rate-limit management tests: Retry-After, quarantine, 402 fast-fail, pacing, ledger."""
from __future__ import annotations
import time
import pytest

from app.gateway.codecraft import (
    DailyQuotaExhausted,
    Gateway,
    OutOfFunds,
    ProviderUnavailable,
    _daily_reset_from,
    _retry_after,
)
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_provider_keys(monkeypatch):
    """Exercise key rotation with deterministic offline compatibility keys."""
    monkeypatch.setattr(settings, "EXPLABS_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_KEY", "")
    for index, value in enumerate(("test-key-1", "test-key-2", "test-key-3", "test-key-4", "test-key-5"), 1):
        monkeypatch.setattr(settings, f"CODECRAFT_KEY_{index}", value)

class _Resp:
    def __init__(self, headers):
        self.headers = headers

class _E401(Exception):
    status_code = 401

class _E402(Exception):
    status_code = 402
    code = "insufficient_funds"

def test_retry_after_parse(monkeypatch):
    monkeypatch.setattr("app.config.settings.RATE_MAX_COOLDOWN_S", 300.0)
    assert _retry_after(Exception("x"), default=60.0) == 60.0  # no response at all
    e = Exception("429")
    e.response = _Resp({"retry-after": "7"})  # type: ignore
    assert _retry_after(e) == 7.0
    e2 = Exception("429")
    e2.response = _Resp({"retry-after": "99999"})  # type: ignore
    assert _retry_after(e2) == 300.0  # clamped

def test_402_quarantines_and_rotates(monkeypatch):
    gw = Gateway()
    gw.day_usage = 0  # hermetic: live eval burn must not trip caps in unit tests
    gw.session_usage = {}
    calls = []
    def boom_once_then_ok(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise _E402("key empty")
        return '{"ok": true}', 10
    monkeypatch.setattr(gw, "_call_once", boom_once_then_ok)
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    assert gw.complete_json(role="technical", session_id="t", system="s", user="u") == '{"ok": true}'
    assert len(calls) == 2  # quarantined first key, rotated to next

def test_402_everywhere_raises_out_of_funds(monkeypatch):
    gw = Gateway()
    calls = []
    def boom(*a, **k):
        calls.append(1)
        raise _E402("out of funds")
    monkeypatch.setattr(gw, "_call_once", boom)
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    with pytest.raises(OutOfFunds):
        gw.complete_json(role="technical", session_id="t", system="s", user="u")
    assert len(calls) == len(gw.clients)  # tried every key exactly once, then stopped

def test_401_quarantines_key_and_rotates(monkeypatch):
    from app.config import settings as _s
    gw = Gateway()
    gw.day_usage = 0  # hermetic: live eval burn must not trip caps in unit tests
    gw.session_usage = {}
    seen = []
    def flaky(client, *a, **k):
        seen.append(client)
        if len(seen) == 1:
            raise _E401("revoked")
        return '{"ok": true}', 10
    monkeypatch.setattr(gw, "_call_once", flaky)
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    assert gw.complete_json(role="technical", session_id="t", system="s", user="u") == '{"ok": true}'
    assert len(seen) == 2 and seen[0] is not seen[1]
    dead_idx = gw.clients.index(seen[0])
    assert dead_idx in gw._dead and dead_idx in _s.ANALYST_KEY_IDXS  # analyst key quarantined

def test_all_auth_failures_are_actionable_and_manual_reset_revalidates(monkeypatch):
    gw = Gateway()
    gw.day_usage = 0
    gw.session_usage = {}
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)

    def rejected(*a, **k):
        raise _E401("revoked")

    monkeypatch.setattr(gw, "_call_once", rejected)
    with pytest.raises(ProviderUnavailable, match="provider credentials"):
        gw.complete_json(role="technical", session_id="auth-failure", system="s", user="u")

    gw.reset_quarantined_keys()
    assert gw._dead == set()
    assert gw._dead_reason == {}
    monkeypatch.setattr(gw, "_call_once", lambda *a, **k: ('{"ok": true}', 10))
    assert gw.complete_json(role="technical", session_id="auth-retry", system="s", user="u") == '{"ok": true}'

def test_pacing_enforced():
    gw = Gateway()
    gw._pace(0)
    t0 = time.monotonic()
    import app.config as C
    old = C.settings.RATE_MIN_INTERVAL_S
    C.settings.RATE_MIN_INTERVAL_S = 0.05
    try:
        gw._pace(0)
    finally:
        C.settings.RATE_MIN_INTERVAL_S = old
    assert time.monotonic() - t0 >= 0.04


def test_parallel_callers_reserve_distinct_rate_limit_slots(monkeypatch):
    import threading
    from types import SimpleNamespace
    import app.gateway.codecraft as C
    gw = Gateway()
    waits = []
    monkeypatch.setattr(C.settings, "RATE_MIN_INTERVAL_S", 1.0)
    monkeypatch.setattr(C, "time", SimpleNamespace(monotonic=lambda: 100.0, sleep=waits.append))
    barrier = threading.Barrier(5)
    def caller():
        barrier.wait()
        gw._pace(0)
    threads = [threading.Thread(target=caller) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(waits) == [1.0, 2.0, 3.0, 4.0]
    assert gw._last_call[0] == 104.0

def test_daily_ledger_persists():
    from datetime import date
    from app.db import sqlite_conn
    gw = Gateway()
    gw.day_usage = 0  # hermetic: live eval burn must not trip caps in unit tests
    gw.session_usage = {}
    before = sqlite_conn().execute(
        "SELECT tokens FROM usage_daily WHERE day=?", (date.today().isoformat(),)).fetchone()
    before = before[0] if before else 0
    gw._track("ledger-test", 100)
    after = sqlite_conn().execute(
        "SELECT tokens FROM usage_daily WHERE day=?", (date.today().isoformat(),)).fetchone()[0]
    assert after - before == 100


def _daily_429(reset_epoch: float | None = None) -> Exception:
    """A faithful OpenRouter free-tier daily-limit 429 (observed 2026-10-27)."""
    import httpx
    import openai

    headers = {"x-ratelimit-remaining": "0"}
    if reset_epoch is not None:
        headers["x-ratelimit-reset"] = str(int(reset_epoch * 1000))
    body = {"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429,
                      "metadata": {"limit_source": "openrouter_free_tier_daily"}}}
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, headers=headers, json=body, request=request)
    return openai.RateLimitError("Rate limit exceeded: free-models-per-day",
                                 response=response, body=body)


def test_daily_reset_detector_matches_observed_provider_response():
    assert _daily_reset_from(_daily_429(reset_epoch=time.time() + 7200)) is not None
    assert _daily_reset_from(_daily_429()) is not None  # falls back to next UTC midnight


def test_daily_429_fails_fast_not_with_retry_storm(monkeypatch):
    """All keys blocked for the day: stop immediately, never re-bill a doomed call.

    2026-10-27 14:05 IST: every post-quota session died after the same 429 wave
    because the gateway treated the daily limit like an ordinary burst cooldown.
    """
    gw = Gateway()
    gw.day_usage = 0
    gw.session_usage = {}
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    calls = []
    def boom(*a, **k):
        calls.append(1)
        raise _daily_429()
    monkeypatch.setattr(gw, "_call_once", boom)
    with pytest.raises(DailyQuotaExhausted) as info:
        gw.complete_json(role="technical", session_id="t", system="s", user="u")
    assert len(calls) == len(gw.clients)  # one attempt per key, no second pass
    assert info.value.reset_at is not None and info.value.reset_at > time.time()
    assert "resets" in str(info.value)
    # Pre-flight: later calls must fail before reaching the provider at all.
    with pytest.raises(DailyQuotaExhausted):
        gw.complete_json(role="technical", session_id="t2", system="s", user="u")
    assert len(calls) == len(gw.clients)


def test_daily_reset_header_sets_provider_reset(monkeypatch):
    gw = Gateway()
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    reset_epoch = time.time() + 7200

    def boom(*a, **k):
        raise _daily_429(reset_epoch=reset_epoch)

    monkeypatch.setattr(gw, "_call_once", boom)
    with pytest.raises(DailyQuotaExhausted):
        gw.complete_json(role="technical", session_id="t", system="s", user="u")
    status = gw.quota_status()
    assert status["exhausted"] is True
    assert abs(status["seconds_until_reset"] - 7200) < 60
    assert status["reset_ist"]


def test_burst_429_still_rotates_without_daily_state(monkeypatch):
    import httpx
    import openai

    gw = Gateway()
    gw.day_usage = 0
    gw.session_usage = {}
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, headers={"retry-after": "2"},
                              json={"error": {"message": "Rate limit exceeded: please try again soon."}},
                              request=request)
    burst = openai.RateLimitError("Rate limit exceeded", response=response, body=None)
    seen = []
    def flaky(client, *a, **k):
        seen.append(client)
        if len(seen) == 1:
            raise burst
        return '{"ok": true}', 10
    monkeypatch.setattr(gw, "_call_once", flaky)
    assert gw.complete_json(role="technical", session_id="t", system="s", user="u") == '{"ok": true}'
    assert gw._daily_quota_until == {}  # a burst 429 must never read as a daily quota


def test_local_request_cap_blocks_preflight(monkeypatch):
    gw = Gateway()
    monkeypatch.setattr(settings, "DAILY_REQUEST_CAP", 2)
    gw.day_requests = 2
    calls = []

    def ok(*a, **k):
        calls.append(1)
        return '{"ok": true}', 10

    monkeypatch.setattr(gw, "_call_once", ok)
    with pytest.raises(DailyQuotaExhausted):
        gw.complete_json(role="technical", session_id="t", system="s", user="u")
    assert calls == []
    assert gw.quota_status()["exhausted"] is True


def test_request_ledger_persists():
    from datetime import date
    from app.db import sqlite_conn
    gw = Gateway()
    gw.day_usage = 0  # hermetic: live eval burn must not trip caps in unit tests
    gw.session_usage = {}
    before = sqlite_conn().execute(
        "SELECT requests FROM usage_daily WHERE day=?", (date.today().isoformat(),)).fetchone()
    before = before[0] if before else 0
    gw._track("request-ledger-test", 10)
    after = sqlite_conn().execute(
        "SELECT requests FROM usage_daily WHERE day=?", (date.today().isoformat(),)).fetchone()[0]
    assert after - before == 1
    assert gw.day_requests == before + 1


def test_quota_status_reloads_on_day_change(monkeypatch):
    from datetime import date
    gw = Gateway()
    gw.day_requests = 99
    gw.day_usage = 999999
    gw._day = None  # simulate a stale day
    monkeypatch.setattr(gw, "_load_day", lambda: (date.today(), 0, 0, 0.0, ""))
    status = gw.quota_status()
    assert status["exhausted"] is False and status["requests_today"] == 0


def test_persisted_quota_reset_survives_restart(monkeypatch):
    """A backend restart during quota exhaustion must keep failing fast."""
    from datetime import date
    from app.db import sqlite_conn
    reset_epoch = time.time() + 3600
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    gw = Gateway()
    gw.day_usage = 0
    gw.session_usage = {}

    def boom(*a, **k):
        raise _daily_429(reset_epoch=reset_epoch)

    monkeypatch.setattr(gw, "_call_once", boom)
    try:
        with pytest.raises(DailyQuotaExhausted):
            gw.complete_json(role="technical", session_id="t", system="s", user="u")
        # A brand-new Gateway instance (restart) reads the persisted reset.
        reloaded = Gateway()
        assert reloaded._daily_quota_until and all(
            abs(v - reset_epoch) < 1 for v in reloaded._daily_quota_until.values())
        with pytest.raises(DailyQuotaExhausted):
            reloaded.complete_json(role="technical", session_id="t2", system="s", user="u")
    finally:
        # Never leak persisted quota state into other hermetic tests.
        sqlite_conn().execute("UPDATE usage_daily SET quota_reset=0 WHERE day=?",
                              (date.today().isoformat(),))
        sqlite_conn().commit()
