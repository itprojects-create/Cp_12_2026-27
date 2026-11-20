from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.api.stocks import stock_symbol, website_auth
from app.data.fyers_provider import fyers
from app.data.live_market import HISTORY_INTERVALS, INDEX_STREAM, market
from quantplus_intelligence.market_data import market_data

router = APIRouter(prefix="/api/v1/market", dependencies=[Depends(website_auth)])


@router.get("/overview")
async def overview():
    """Provider-backed index overview for the authenticated terminal dashboard."""
    session = await market_data.session()
    names = ("NIFTY", "BANK", "VIX", "SENSEX")
    labels = {
        "NIFTY": ("NIFTY 50", "index", "INR"),
        "BANK": ("BANK NIFTY", "index", "INR"),
        "VIX": ("INDIA VIX", "index", "INR"),
        "SENSEX": ("SENSEX", "index", "INR"),
    }
    quotes = await market_data.indices(session)
    yahoo_indexes = {
        "NIFTY": "^NSEI",
        "BANK": "^NSEBANK",
        "VIX": "^INDIAVIX",
        "SENSEX": "^BSESN",
    }
    for name in names:
        if name in quotes:
            continue
        try:
            quotes[name] = await market.yahoo_index_quote(name, yahoo_indexes[name])
        except Exception:
            continue

    instruments = []
    for order, name in enumerate(names, 1):
        quote = quotes.get(name)
        title, kind, currency = labels[name]
        instruments.append({
            "symbol": name,
            "name": title,
            "kind": kind,
            "currency": currency,
            "value": quote.get("price") if quote else None,
            "change_abs": quote.get("change") if quote else None,
            "change_pct": quote.get("change_pct") if quote else None,
            "source": quote.get("source") if quote else None,
            "delayed": quote.get("delayed", False) if quote else None,
            "stale": quote.get("stale", True) if quote else True,
            "market_session": quote.get("market_session") if quote else session,
            "as_of": quote.get("as_of") if quote else None,
            "updated_at": quote.get("received_at") if quote else None,
            "sort_order": order,
        })
    available = [item for item in instruments if item["value"] is not None]
    source = "fyers" if any(item["source"] == "fyers" for item in available) else "yahoo" if available else None
    return {
        "instruments": instruments,
        "source": source,
        "market_session": session,
        "data_quality": "GOOD" if len(available) == len(instruments) and source == "fyers" else "PARTIAL" if available else "DEGRADED",
        "updated_at": max((item["updated_at"] or "" for item in available), default=None),
    }


@router.get("/overview/stream")
async def overview_stream(request: Request):
    """Server-sent index overview: a full snapshot, then each index tick as it arrives.

    The snapshot repeats every 30 seconds so indices without a socket feed
    (SENSEX, or every index while FYERS is signed out) still update.
    """
    async def events():
        queue = asyncio.Queue(maxsize=64)
        try:
            await market.subscribe_indices(queue)
            yield f"event: overview\ndata: {json.dumps(await overview())}\n\n"
            next_snapshot = asyncio.get_running_loop().time() + 30
            while not await request.is_disconnected():
                timeout = max(0.5, next_snapshot - asyncio.get_running_loop().time())
                try:
                    tick = await asyncio.wait_for(queue.get(), timeout=min(timeout, 15))
                    name = INDEX_STREAM.get(tick.get("symbol"))
                    if name:
                        yield "event: tick\ndata: " + json.dumps({
                            "symbol": name, "value": tick.get("price"), "change_abs": tick.get("change"),
                            "change_pct": tick.get("change_pct"), "source": tick.get("source"),
                            "delayed": tick.get("delayed"), "stale": tick.get("stale"),
                            "market_session": tick.get("market_session"), "as_of": tick.get("as_of"),
                            "updated_at": tick.get("received_at")}) + "\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                if asyncio.get_running_loop().time() >= next_snapshot:
                    next_snapshot = asyncio.get_running_loop().time() + 30
                    try:
                        yield f"event: overview\ndata: {json.dumps(await overview())}\n\n"
                    except Exception:
                        yield ": snapshot unavailable\n\n"
        finally:
            await market.unsubscribe_indices(queue)
    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


OPTION_UNDERLYINGS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}
_option_chain_cache: dict = {}


def _num(value):
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def normalize_option_chain(underlying: str, raw: dict) -> dict:
    """Pair FYERS call/put rows by strike; values are provider observations only."""
    data = raw.get("data") or {}
    rows = data.get("optionsChain") or []
    spot = None
    strikes: dict[float, dict] = {}
    for row in rows:
        kind = str(row.get("option_type") or "").upper()
        strike = _num(row.get("strike_price"))
        if kind not in ("CE", "PE"):
            spot = _num(row.get("ltp")) if spot is None else spot
            continue
        if strike is None or strike <= 0:
            continue
        side = {
            "symbol": row.get("symbol"), "ltp": _num(row.get("ltp")), "change": _num(row.get("ltpch")),
            "change_pct": _num(row.get("ltpchp")), "oi": _num(row.get("oi")), "oi_change": _num(row.get("oich")),
            "volume": _num(row.get("volume")), "bid": _num(row.get("bid")), "ask": _num(row.get("ask")),
        }
        strikes.setdefault(strike, {"strike": strike, "call": None, "put": None})["call" if kind == "CE" else "put"] = side
    expiries = []
    for item in data.get("expiryData") or []:
        if item.get("expiry") and item.get("date"):
            expiries.append({"expiry": str(item["expiry"]), "date": str(item["date"])})
    call_oi = sum((r["call"] or {}).get("oi") or 0 for r in strikes.values())
    put_oi = sum((r["put"] or {}).get("oi") or 0 for r in strikes.values())
    return {
        "underlying": underlying, "spot": spot, "source": "fyers", "delayed": False,
        "as_of": datetime.now(timezone.utc).isoformat(), "expiries": expiries,
        "rows": [strikes[k] for k in sorted(strikes)],
        "call_oi": call_oi or None, "put_oi": put_oi or None,
        "pcr": (put_oi / call_oi) if call_oi else None,
    }


@router.get("/{symbol}/option-chain")
async def option_chain(symbol: str, strikes: int = 12, expiry: str = ""):
    """Observed FYERS option chain for an index or F&O stock (display only)."""
    name = symbol.upper()
    provider_symbol = OPTION_UNDERLYINGS.get(name) or f"NSE:{stock_symbol(name)}-EQ"
    if not 2 <= strikes <= 40:
        raise HTTPException(422, "Request between 2 and 40 strikes either side")
    if expiry and not expiry.isdigit():
        raise HTTPException(422, "Expiry must be the provider's expiry timestamp")
    if not fyers.token():
        raise HTTPException(503, "Option chains need a FYERS sign-in; no delayed source is available")
    key = (provider_symbol, strikes, expiry)
    cached = _option_chain_cache.get(key)
    if cached and time.monotonic() - cached[0] < 15:
        return cached[1]
    try:
        raw = await fyers.get("options-chain-v3", {"symbol": provider_symbol, "strikecount": strikes, "timestamp": expiry})
    except Exception:
        raise HTTPException(502, "Option chain unavailable from FYERS; retry shortly")
    payload = normalize_option_chain(name, raw)
    if not payload["rows"]:
        raise HTTPException(404, f"No listed options for {name}")
    _option_chain_cache[key] = (time.monotonic(), payload)
    return payload


@router.get("/{symbol}/quote")
async def quote_snapshot(symbol: str):
    """Return one current stock quote for live valuation and grounded AI context."""
    symbol = stock_symbol(symbol)
    result = await market_data.stock(symbol)
    quote = result.get("quote")
    if quote:
        return quote
    try:
        return await market.yahoo_quote(symbol)
    except Exception:
        raise HTTPException(502, "Current market quote unavailable")


@router.get("/stream")
async def stream_many(symbols: str, request: Request):
    names = list(dict.fromkeys(stock_symbol(value.strip()) for value in symbols.split(",")))
    if not 1 <= len(names) <= 50:
        raise HTTPException(422, "Subscribe to between 1 and 50 NSE symbols")

    async def events():
        yield ': connected\n\n'
        queue = asyncio.Queue(maxsize=max(50, len(names) * 2))
        try:
            await market.subscribe_many(names, queue)
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
        finally:
            await market.unsubscribe_many(names, queue)
    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


@router.get("/{symbol}/history")
async def history(symbol: str, range: Literal["1D", "1W", "1M", "6M", "1Y", "5Y"] = "1D",
                  interval: Literal["1m", "5m", "15m", "60m", "1d"] | None = None):
    symbol = stock_symbol(symbol)
    if interval is not None and interval not in HISTORY_INTERVALS[range]:
        raise HTTPException(422, f"{interval} bars are not available for the {range} range")
    try:
        return await (market.history(symbol, range, interval) if interval else market.history(symbol, range))
    except Exception:
        raise HTTPException(502, "Historical market data unavailable; retry shortly")


@router.get("/{symbol}/stream")
async def stream(symbol: str, request: Request):
    symbol = stock_symbol(symbol)

    async def events():
        queue = asyncio.Queue(maxsize=1)
        try:
            await market.subscribe(symbol, queue)
            yield ': connected\n\n'
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
        finally:
            await market.unsubscribe(symbol, queue)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})
