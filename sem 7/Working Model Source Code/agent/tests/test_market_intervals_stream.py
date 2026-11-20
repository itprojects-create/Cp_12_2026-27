"""Chart intervals and the index overview stream."""
import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.data.fyers_provider import fyers
from app.data.live_market import HISTORY_INTERVALS, LiveMarket


@pytest.fixture(autouse=True)
def no_live_fyers_credentials(monkeypatch):
    monkeypatch.setattr(fyers, "token", lambda: "")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("QP_DB_PATH", str(tmp_path / "website.db"))
    monkeypatch.setattr(settings, "WEBSITE_API_KEY", "test-website-key")
    return TestClient(app_instance(), headers={"X-Quantplus-Key": "offline-internal-test-key"})


def app_instance():
    from app.main import app
    return app


def test_history_api_rejects_intervals_outside_the_range(client):
    headers = {"X-Quantplus-Key": "test-website-key"}
    response = client.get("/api/v1/market/RELIANCE/history?range=1Y&interval=1m", headers=headers)
    assert response.status_code == 422
    assert client.get("/api/v1/market/RELIANCE/history?range=1D&interval=2h", headers=headers).status_code == 422


def test_yahoo_fallback_requests_the_selected_interval(monkeypatch):
    async def check():
        market = LiveMarket()
        chart = AsyncMock(return_value={"timestamp": [10, 20], "indicators": {"quote": [{
            "open": [100, 101], "high": [102, 103], "low": [99, 100], "close": [101, 102], "volume": [5, 6]}]}})
        monkeypatch.setattr(market, "yahoo_chart", chart)
        payload = await market.history("RELIANCE", "1D", "5m")
        assert chart.await_args.args == ("RELIANCE", "1d", "5m")
        assert payload["interval"] == "5m" and len(payload["candles"]) == 2
        # Default and explicit intervals are cached separately.
        await market.history("RELIANCE", "1D")
        assert chart.await_args.args == ("RELIANCE", "1d", "1m")
        with pytest.raises(ValueError):
            await market.history("RELIANCE", "5Y", "1m")

    asyncio.run(check())


def test_every_range_allows_its_default_interval():
    from app.data.live_market import HISTORY_DEFAULT_INTERVAL
    for range_name, interval in HISTORY_DEFAULT_INTERVAL.items():
        assert interval in HISTORY_INTERVALS[range_name]


def test_index_ticks_reach_overview_subscribers_and_never_regress():
    async def check():
        market = LiveMarket()
        queue = asyncio.Queue(maxsize=8)
        await market.subscribe_indices(queue)
        now = time.time()
        market._tick({"symbol": "NSE:NIFTY50-INDEX", "ltp": 24800.5, "prev_close_price": 24700,
                      "exch_feed_time": now})
        tick = queue.get_nowait()
        assert tick["symbol"] == "NIFTY50-INDEX" and tick["price"] == 24800.5
        assert round(tick["change_pct"], 3) == round((24800.5 / 24700 - 1) * 100, 3)
        market._tick({"symbol": "NSE:NIFTY50-INDEX", "ltp": 1, "prev_close_price": 24700,
                      "exch_feed_time": now - 120})
        assert queue.empty()  # An older observation cannot replace a newer one.
        await market.unsubscribe_indices(queue)
        assert "NIFTY50-INDEX" not in market.listeners

    asyncio.run(check())


def test_option_chain_pairs_strikes_and_requires_fyers(client, monkeypatch):
    from app.api import market as market_api
    headers = {"X-Quantplus-Key": "test-website-key"}
    assert client.get("/api/v1/market/NIFTY/option-chain", headers=headers).status_code == 503
    monkeypatch.setattr(fyers, "token", lambda: "TEST-100:mock")
    raw = {"s": "ok", "data": {
        "expiryData": [{"date": "30-10-2026", "expiry": "1793345400"}],
        "optionsChain": [
            {"option_type": "", "strike_price": -1, "ltp": 24812.4, "symbol": "NSE:NIFTY50-INDEX"},
            {"option_type": "CE", "strike_price": 24800, "ltp": 120.5, "oi": 1000, "oich": 50, "volume": 9},
            {"option_type": "PE", "strike_price": 24800, "ltp": 98.0, "oi": 1500, "oich": -20, "volume": 7},
            {"option_type": "CE", "strike_price": 24900, "ltp": 70.0, "oi": 500},
        ]}}
    calls = []

    async def fake_get(path, params=None):
        calls.append((path, params))
        return raw
    monkeypatch.setattr(fyers, "get", fake_get)
    market_api._option_chain_cache.clear()
    response = client.get("/api/v1/market/NIFTY/option-chain?strikes=5", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert calls[0] == ("options-chain-v3", {"symbol": "NSE:NIFTY50-INDEX", "strikecount": 5, "timestamp": ""})
    assert body["spot"] == 24812.4 and [row["strike"] for row in body["rows"]] == [24800, 24900]
    assert body["rows"][0]["put"]["oi"] == 1500 and body["rows"][1]["put"] is None
    assert body["pcr"] == 1500 / 1500
    assert body["expiries"] == [{"expiry": "1793345400", "date": "30-10-2026"}]
    assert client.get("/api/v1/market/NIFTY/option-chain?expiry=abc", headers=headers).status_code == 422
