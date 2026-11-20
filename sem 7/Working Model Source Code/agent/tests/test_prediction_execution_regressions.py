"""Offline execution measurements and regressions; use a temporary working directory.

Benchmark (five cold runs, 10-second cutoff per run):
  python -m pytest <backend>/tests/test_prediction_execution_regressions.py -k benchmark -s -q
All providers/models are fake, sockets are denied, and only temporary SQLite is used.
"""
from __future__ import annotations

import json
import _socket
import socket
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
from fastapi import BackgroundTasks
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from tenacity import wait_fixed


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access forbidden in prediction execution tests")

    def connect(sock, address):
        # Windows implements asyncio's private socketpair using loopback TCP.
        if sys._getframe(1).f_code is socket.socketpair.__code__:
            return _socket.socket.connect(sock, address)
        forbidden()

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setenv("QP_DB_PATH", str(tmp_path / "execution.db"))
    from app.config import settings
    from app.api import stocks
    from app import control, log

    monkeypatch.setattr(log, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(control, "is_engaged", lambda: False)
    monkeypatch.setattr(type(settings), "codecraft_keys", lambda self: ["offline-one", "offline-two"])
    monkeypatch.setattr(settings, "ANALYST_KEY_IDXS", [0, 1])
    monkeypatch.setattr(settings, "RATE_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(settings, "STOCK_PREDICTION_REFRESH_SECONDS", 900)
    monkeypatch.setattr(settings, "STOCK_PREDICTION_MAX_STALE_SECONDS", 86400)
    monkeypatch.setattr(settings, "STOCK_PREDICTION_MAX_CONCURRENT", 2)
    monkeypatch.setattr(settings, "STOCK_PREDICTION_WARM_ENABLED", True)
    monkeypatch.setattr(settings, "STOCK_PREDICTION_WARM_SYMBOLS", "FAKE")
    monkeypatch.setattr(stocks, "_active_sessions", set())
    monkeypatch.setattr(stocks, "_recent_symbols", {})
    monkeypatch.setattr(stocks, "_warm_retry_after", {})
    monkeypatch.setattr(stocks, "_slots", threading.BoundedSemaphore(2))


def _http_error(code):
    request = httpx.Request("POST", "https://offline.invalid")
    if code == "connection":
        return APIConnectionError(request=request)
    if code == "timeout":
        return APITimeoutError(request=request)
    kind = RateLimitError if code == 429 else APIStatusError
    return kind("synthetic provider error", response=httpx.Response(code, request=request), body=None)


def _gateway(monkeypatch, code):
    from app.gateway.codecraft import Gateway

    gw = Gateway()
    for client in gw.clients:
        client.close()
    attempts = []

    def create(index):
        def result(**kwargs):
            attempts.append(index)
            if index == 0:
                raise _http_error(code)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
                message=SimpleNamespace(content='{"ok":true}'))],
                usage=SimpleNamespace(total_tokens=10))
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=result)))

    gw.clients = [create(0), create(1)]
    # Compress only the configured sleep, preserving the real retry predicate,
    # attempt cap and outer rotation. Production's 2/4/8/16s waits total 30s.
    retrying = Gateway._call_once.retry_with(wait=wait_fixed(0.02))
    monkeypatch.setattr(gw, "_call_once", lambda *a, **k: retrying(gw, *a, **k))
    return gw, attempts


def _seed_failure(age=3600, sid="expired", status="failed: RuntimeError"):
    from app.api import stocks
    from app.db import sqlite_conn

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    conn = sqlite_conn()
    conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                 (sid, "FAKE.NS", cutoff, stocks.prediction_config(), status, None))
    conn.execute("INSERT INTO checkpoints VALUES (?,?,?,?)",
                 (sid, "analyst:news", '{"preserved":true}', cutoff))
    conn.commit()
    return cutoff


def _fake_graph_inputs(monkeypatch):
    from app.agents import _util
    from app.data.yfinance_provider import YFinanceProvider
    from app.data.events import YFinanceEventsProvider
    from app.data.gnews_provider import GNewsProvider
    from app.data.local_store import DeliveryStore

    cutoff = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    index = pd.date_range(end="2026-10-16", periods=420, freq="B", tz="UTC")
    frame = pd.DataFrame({"Open": 100., "High": 101., "Low": 99., "Close": 100.,
                          "Volume": 1000000}, index=index)
    frame["bar_end"] = frame.index + pd.Timedelta(days=1)
    frame["available_at"] = frame["bar_end"] + pd.Timedelta(minutes=15)
    frame["completed"] = True
    locks = {name: threading.Lock() for name in ("FAKE.NS", "^NSEI", "^INDIAVIX")}
    downloaded, calls = set(), []

    def ohlcv(self, instrument, as_of, interval="1d", lookback=120):
        assert as_of == cutoff
        with locks[instrument]:
            if instrument not in downloaded:
                time.sleep(0.08)
                downloaded.add(instrument)
        return frame.loc[frame.available_at <= as_of].tail(lookback).copy()

    def model(*, role, **kwargs):
        calls.append(role)
        time.sleep(0.025)
        if role in ("technical", "fundamentals", "news", "macro", "events"):
            body = {"summary": "Insufficient directional evidence; abstaining.",
                    "signals": [], "confidence": 0.2, "evidence": []}
        elif role in ("bull", "bear"):
            body = {"stance": "long" if role == "bull" else "short",
                    "argument": "No verified directional edge in the provided evidence.",
                    "rebuttal_to": "", "confidence_delta": 0.1}
        elif role == "research_manager":
            body = {"direction": "flat", "conviction": 0.2, "key_evidence": [], "key_risks": []}
        elif role == "devils_advocate":
            body = {"status": "HEALTHY", "core_claim_restated": "No verified directional edge.",
                    "direction_symmetry_check_passed": True, "raw_override_applied": False}
        elif role == "trader":
            body = {"direction": "flat", "size_pct": 0, "entry": 100, "stop": 95, "target": 105}
        elif role.startswith("risk_"):
            body = {"approve": True, "adjusted_size": 0, "notes": "No exposure proposed."}
        else:
            body = {"action": "hold", "size": 0, "rationale": "Insufficient evidence to act."}
        return json.dumps(body)

    monkeypatch.setattr(YFinanceProvider, "ohlcv", ohlcv)
    monkeypatch.setattr(YFinanceEventsProvider, "events", lambda *a, **k: [])
    monkeypatch.setattr(GNewsProvider, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(DeliveryStore, "line", lambda *a, **k: "Delivery data unavailable")
    monkeypatch.setattr(_util.gateway, "complete_json", model)
    return cutoff, calls


def test_benchmark_prediction_execution(monkeypatch, tmp_path):
    from app.api import stocks
    from app.agents import graph
    from app.db import sqlite_conn

    timings = {"cold_full_graph_ms": [], "terminal_401_fallback_ms": []}
    attempts, warm_lags = [], []
    expected = Counter({"technical": 1, "fundamentals": 1, "news": 1, "macro": 1, "events": 1,
        "bull": 2, "bear": 2, "research_manager": 1, "devils_advocate": 1, "trader": 1,
        "risk_agg": 1, "risk_con": 1, "risk_neu": 1, "portfolio_manager": 1})
    for sample in range(5):
        monkeypatch.setenv("QP_DB_PATH", str(tmp_path / f"sample-{sample}.db"))
        cutoff, calls = _fake_graph_inputs(monkeypatch)
        conn = sqlite_conn()
        conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                     ("bench", "FAKE.NS", cutoff.isoformat(), "offline", "queued", None))
        conn.commit()
        start = time.perf_counter()
        result = graph.run_session("bench", "FAKE.NS", cutoff, deadline_s=10)
        timings["cold_full_graph_ms"].append(round(1000 * (time.perf_counter() - start), 3))
        assert Counter(calls) == expected
        assert result.action == "hold" and result.authority == "RESEARCH_ONLY"
        view = stocks.session_view("bench")
        assert view["status"] == "done" and len(view["reports"]) == 5
        assert view["as_of"] == cutoff.isoformat()
        assert len([e for e in view["events"] if e["stage"] == "claim_validation"]) == 5

        gw, seen = _gateway(monkeypatch, 401)
        start = time.perf_counter()
        assert gw.complete_json(role="technical", session_id="retry", system="s", user="u") == '{"ok":true}'
        timings["terminal_401_fallback_ms"].append(round(1000 * (time.perf_counter() - start), 3))
        attempts.append(len(seen))
        _seed_failure()
        _, bg = stocks.warm_next()
        assert len(bg.tasks) == 1
        sid, _, as_of = bg.tasks[0].args
        warm_lags.append(round((datetime.now(timezone.utc) - as_of).total_seconds(), 3))
        # Never execute a scheduled warm task in the benchmark.
        stocks._active_sessions.discard(sid)
        stocks._slots.release()
    print("\nPREDICTION_BENCHMARK=" + json.dumps({
        "samples_ms": timings,
        "median_ms": {k: round(statistics.median(v), 3) for k, v in timings.items()},
        "http_attempts": attempts, "warmer_cutoff_lag_seconds": warm_lags,
        "model_calls_per_full_graph": sum(expected.values()),
        "workload": "5 cold isolated full graphs; 80ms/provider, 25ms/model; terminal retry sleep=20ms",
    }, sort_keys=True))


@pytest.mark.parametrize("code", [400, 401, 402, 403, 404, 422, 429])
def test_rejected_http_calls_rotate_without_transport_backoff(monkeypatch, code):
    gw, attempts = _gateway(monkeypatch, code)
    assert gw.complete_json(role="technical", session_id="terminal", system="s", user="u") == '{"ok":true}'
    assert attempts == [0, 1]


@pytest.mark.parametrize("code", [408, 500, 502, 503, 504, "connection", "timeout"])
def test_transient_http_errors_retain_the_transport_retry_budget(monkeypatch, code):
    gw, attempts = _gateway(monkeypatch, code)
    assert gw.complete_json(role="technical", session_id="transient", system="s", user="u") == '{"ok":true}'
    assert attempts == [0] * 5 + [1]


@pytest.mark.parametrize("status", ["failed: RuntimeError", "running", "queued"])
def test_automatic_refresh_does_not_resume_an_expired_cutoff(status):
    from app.api import stocks
    from app.db import sqlite_conn

    old_cutoff = _seed_failure(status=status)
    _, bg = stocks.warm_next()
    assert len(bg.tasks) == 1
    sid, _, as_of = bg.tasks[0].args
    assert sid != "expired"
    assert 0 <= (datetime.now(timezone.utc) - as_of).total_seconds() < 5
    assert sqlite_conn().execute("SELECT as_of, status FROM sessions WHERE id='expired'").fetchone() == (old_cutoff, status)
    assert sqlite_conn().execute("SELECT payload FROM checkpoints WHERE session_id='expired'").fetchone() == ('{"preserved":true}',)


def test_explicit_retry_preserves_original_cutoff_and_checkpoints():
    from app.api import stocks

    cutoff = _seed_failure()
    bg = BackgroundTasks()
    first = stocks.prediction("FAKE", bg, retry=True)
    assert first["id"] == "expired" and len(bg.tasks) == 1
    assert bg.tasks[0].args[2].isoformat() == cutoff
    again = BackgroundTasks()
    assert stocks.prediction("FAKE", again, retry=True)["id"] == first["id"]
    assert not again.tasks


def test_expired_active_research_remains_single_flight():
    from app.api import stocks

    cutoff = _seed_failure(status="running")
    stocks._active_sessions.add("expired")
    _, warm = stocks.warm_next()
    assert not warm.tasks
    bg = BackgroundTasks()
    result = stocks.prediction("FAKE", bg)
    assert result["id"] == "expired" and result["as_of"] == cutoff
    assert not bg.tasks


def test_recent_orphan_still_resumes_its_checkpoints():
    from app.api import stocks

    cutoff = _seed_failure(age=100, status="running")
    _, bg = stocks.warm_next()
    assert len(bg.tasks) == 1
    assert bg.tasks[0].args[0] == "expired"
    assert bg.tasks[0].args[2].isoformat() == cutoff


def test_macro_fetches_independent_indices_together_in_original_prompt_order(monkeypatch):
    from app import schemas as S
    from app.agents import analysts

    barrier = threading.Barrier(2)
    cutoff = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    requests, contexts = [], []

    def ohlcv(self, instrument, as_of, interval, lookback):
        requests.append((instrument, as_of, interval, lookback))
        barrier.wait(timeout=2)
        return pd.DataFrame({"Close": [100., 101.]})

    def validated(role, sid, system, user, schema, fixed, **kwargs):
        contexts.append((user, kwargs))
        return S.AnalystReport(agent="macro", summary="Observed index data only.", confidence=0.2)

    monkeypatch.setattr(analysts.YFinanceProvider, "ohlcv", ohlcv)
    monkeypatch.setattr(analysts, "call_json", validated)
    result = analysts.run_macro("FAKE.NS", cutoff, "1d", "macro-parallel")
    assert result.agent == "macro"
    assert set(requests) == {(sym, cutoff, "1d", 25) for sym in ("^NSEI", "^INDIAVIX")}
    user, kwargs = contexts[0]
    assert user.index("^NSEI:") < user.index("^INDIAVIX:")
    assert "nifty_last=101.00" in user and "indiavix_last=101.00" in user
    assert kwargs == {"grounding": user, "as_of": cutoff}


def test_macro_feed_failure_is_explicit_and_does_not_remove_other_index(monkeypatch):
    from app import schemas as S
    from app.agents import analysts

    def ohlcv(self, instrument, *args, **kwargs):
        if instrument == "^NSEI":
            raise TimeoutError("synthetic timeout")
        return pd.DataFrame({"Close": [10., 11.]})

    def validated(role, sid, system, user, *args, **kwargs):
        assert "^NSEI: unavailable (TimeoutError)" in user
        assert "^INDIAVIX: indiavix_last=11.00" in user
        return S.AnalystReport(agent="macro", summary="Partial observed index evidence.", confidence=0.2)

    monkeypatch.setattr(analysts.YFinanceProvider, "ohlcv", ohlcv)
    monkeypatch.setattr(analysts, "call_json", validated)
    analysts.run_macro("FAKE.NS", datetime.now(timezone.utc), "1d", "macro-failure")
