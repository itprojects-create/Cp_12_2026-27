"""Shared FYERS tick feed with timestamped Yahoo snapshots as fallback.

This is a display feed, separate from the audited PIT research providers.
No fabricated prices and no broker order calls.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from app.config import settings
from app.data.fyers_provider import fyers, FyersUnavailable

IST = timezone(timedelta(hours=5, minutes=30))

# Chart ranges, their default bar interval, and the intervals each range allows.
HISTORY_DAYS = {"1D": 1, "1W": 7, "1M": 31, "6M": 184, "1Y": 365, "5Y": 1826}
HISTORY_DEFAULT_INTERVAL = {"1D": "1m", "1W": "15m", "1M": "60m", "6M": "1d", "1Y": "1d", "5Y": "1d"}
HISTORY_INTERVALS = {
    "1D": ("1m", "5m", "15m"),
    "1W": ("1m", "5m", "15m", "60m"),
    "1M": ("5m", "15m", "60m", "1d"),
    "6M": ("60m", "1d"),
    "1Y": ("1d",),
    "5Y": ("1d",),
}
# Yahoo keeps one-minute bars for 7 days and other intraday bars for 60 days.
YAHOO_PERIOD = {"1D": "1d", "1W": "5d", "1M": "1mo", "6M": "6mo", "1Y": "1y", "5Y": "5y"}
INDEX_STREAM = {"NIFTY50-INDEX": "NIFTY", "NIFTYBANK-INDEX": "BANK", "INDIAVIX-INDEX": "VIX"}
# A provider 429/backoff is waited out before the labelled Yahoo fallback:
# a 50-symbol board burst otherwise cascades one rejection into instant
# Yahoo degradation for every unlucky caller (observed 2026-10-27).
HISTORY_TRANSIENT_RETRIES = 2
HISTORY_TRANSIENT_WAIT_CAP = 5.0


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def quote_payload(symbol, price, previous, timestamp, source, **fields):
    price, previous = number(price), number(previous)
    timestamp = number(timestamp)
    if not price or price <= 0 or not timestamp:
        raise ValueError("Provider returned no valid timestamped quote")
    now = datetime.now(timezone.utc)
    local = now.astimezone(IST)
    in_session = local.weekday() < 5 and (9, 15) <= (local.hour, local.minute) < (15, 30)
    return {"symbol": symbol, "price": price,
            "previous_close": previous,
            "change": price - previous if previous else None,
            "change_pct": (price / previous - 1) * 100 if previous else None,
            "source": source, "delayed": source == "yahoo",
            "as_of": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "received_at": now.isoformat(),
            "stale": now.timestamp() - timestamp > 60,
            "market_session": "open" if in_session else "closed",
            **{k: number(v) for k, v in fields.items()}}


class LiveMarket:
    def __init__(self):
        self.shared_stream_version = 1
        self.listeners = {}
        self.tasks = {}
        self.quotes = {}
        self.fyers_quotes = {}
        self.last_fyers = {}
        self.history_cache = {}
        self.history_locks = {}
        self.socket = None
        self.connected = False
        self.loop = None
        self.client = None
        self._socket_attempt = 0.0
        self.socket_lock = asyncio.Lock()
        self.socket_close_lock = asyncio.Lock()
        self._socket_token = ""
        self.bootstrap_tokens = {}
        self.snapshot_attempts = {}
        self.depth_raw = {}
        self.deep_symbols = set()
        self.depth_received = {}
        self.yahoo_slots = asyncio.Semaphore(4)

    async def _http(self):
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return self.client

    async def yahoo_chart(self, symbol, period="1d", interval="1m"):
        client = await self._http()
        async with self.yahoo_slots:
            response = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol + '.NS', safe='')}",
                params={"range": period, "interval": interval, "includePrePost": "false"})
        response.raise_for_status()
        result = response.json()["chart"].get("result")
        if not result:
            raise ValueError("Yahoo returned no market data")
        return result[0]

    async def yahoo_index_chart(self, yahoo_symbol, period="1d", interval="1m"):
        """Read an index chart without applying the NSE equity ``.NS`` suffix."""
        client = await self._http()
        async with self.yahoo_slots:
            response = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(yahoo_symbol, safe='')}",
                params={"range": period, "interval": interval, "includePrePost": "false"},
            )
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result")
        if not result:
            raise ValueError("Yahoo returned no index data")
        return result[0]

    async def yahoo_index_quote(self, symbol, yahoo_symbol):
        result = await self.yahoo_index_chart(yahoo_symbol)
        meta = result["meta"]
        return quote_payload(
            symbol,
            meta.get("regularMarketPrice"),
            meta.get("chartPreviousClose", meta.get("previousClose")),
            meta.get("regularMarketTime"),
            "yahoo",
        )

    async def yahoo_quote(self, symbol):
        result = await self.yahoo_chart(symbol)
        meta = result["meta"]
        values = result.get("indicators", {}).get("quote", [{}])[0]
        return quote_payload(symbol, meta.get("regularMarketPrice"),
                             meta.get("chartPreviousClose", meta.get("previousClose")),
                             meta.get("regularMarketTime"), "yahoo",
                             open=next((v for v in values.get("open", []) if v is not None), None),
                             high=meta.get("regularMarketDayHigh"),
                             low=meta.get("regularMarketDayLow"), volume=meta.get("regularMarketVolume"))

    async def history(self, symbol, range_name, interval=None):
        interval = interval or HISTORY_DEFAULT_INTERVAL[range_name]
        if interval not in HISTORY_INTERVALS[range_name]:
            raise ValueError(f"{interval} bars are not available for the {range_name} range")
        default = interval == HISTORY_DEFAULT_INTERVAL[range_name]
        key = (symbol, range_name, fyers.token()) if default else (symbol, range_name, interval, fyers.token())
        lock = self.history_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self.history_cache.get(key)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            if fyers.token():
                for attempt in range(HISTORY_TRANSIENT_RETRIES + 1):
                    try:
                        payload = (await fyers.history(symbol, range_name) if default
                                   else await fyers.history(symbol, range_name, interval))
                        self.history_cache[key] = (time.monotonic(), payload)
                        return payload
                    except FyersUnavailable as error:
                        if attempt == HISTORY_TRANSIENT_RETRIES:
                            logging.getLogger("quantplus.market").warning(
                                "fyers_history_fallback symbol=%s range=%s attempts=%s error=%s",
                                symbol, range_name, attempt + 1, error)
                            break
                        wait = min(fyers.budget.retry_after() + 0.05, HISTORY_TRANSIENT_WAIT_CAP)
                        if wait > 0:
                            await asyncio.sleep(wait)
                    except Exception as error:
                        # Credential/parse/provider-data failures cannot recover
                        # by waiting; Yahoo remains an explicitly labelled fallback.
                        logging.getLogger("quantplus.market").warning(
                            "fyers_history_fallback symbol=%s range=%s error=%s",
                            symbol, range_name, error)
                        break
            result = await self.yahoo_chart(symbol, YAHOO_PERIOD[range_name], interval)
            values = result["indicators"]["quote"][0]
            candles = []
            for i, ts in enumerate(result.get("timestamp", [])):
                bar = {k: number(values.get(k, [])[i]) if i < len(values.get(k, [])) else None
                       for k in ("open", "high", "low", "close", "volume")}
                if all(bar[k] is not None for k in ("open", "high", "low", "close")):
                    candles.append({"time": ts, **bar, "volume": bar["volume"] or 0})
            if not candles:
                raise ValueError("No historical candles available")
            payload = {"symbol": symbol, "range": range_name, "interval": interval,
                       "source": "yahoo", "delayed": True, "candles": candles,
                       "as_of": datetime.fromtimestamp(candles[-1]["time"], timezone.utc).isoformat()}
            self.history_cache[key] = (time.monotonic(), payload)
            return payload

    def _publish(self, symbol, payload):
        self.quotes[symbol] = payload
        for queue in self.listeners.get(symbol, set()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)

    def _tick(self, message):
        if not isinstance(message, dict) or not isinstance(message.get("symbol"), str) or not message["symbol"].startswith("NSE:"):
            return
        symbol = message["symbol"][4:].removesuffix("-EQ")
        if symbol in INDEX_STREAM and symbol in self.listeners:
            self._index_tick(symbol, message)
            return
        if symbol not in self.listeners:
            return
        if message.get("type") == "dp" or "bid_price1" in message:
            self.depth_raw.setdefault(symbol, {}).update(message)
            self.depth_received[symbol] = datetime.now(timezone.utc).isoformat()
            previous = self.fyers_quotes.get(symbol)
            if previous:
                payload = {**previous, **self._depth_fields(symbol),
                           "depth_as_of": datetime.now(timezone.utc).isoformat()}
                self.fyers_quotes[symbol] = payload
                self._publish(symbol, payload)
            return
        # A price must be paired with an authentic provider observation time.
        # Metadata-only frames cannot advance an old price's timestamp; neither
        # receipt time nor a previous tick's as_of can timestamp a new price.
        price = number(message.get("ltp"))
        if isinstance(message.get("ltp"), bool) or price is None or price <= 0:
            return
        timestamp = None
        fields = ("exch_feed_time", "last_traded_time") if symbol.endswith("-INDEX") else ("last_traded_time",)
        for field in fields:
            value = number(message.get(field))
            if not isinstance(message.get(field), bool) and value is not None and 0 < value <= time.time() + 60:
                timestamp = value
                break
        if timestamp is None:
            return
        previous = self.fyers_quotes.get(symbol, {})
        try:
            observed = datetime.fromtimestamp(timestamp, timezone.utc)
            previous_time = datetime.fromisoformat(previous["as_of"]) if previous.get("as_of") else None
            if previous_time and observed < previous_time:
                return  # Late/replayed frames cannot regress an observation.
            if previous_time and observed.astimezone(IST).date() != previous_time.astimezone(IST).date():
                previous = {}  # Do not carry yesterday's partial daily fields.
        except (TypeError, ValueError, OverflowError, OSError):
            return
        try:
            payload = quote_payload(symbol, price,
                message.get("prev_close_price", previous.get("previous_close")),
                timestamp,
                "fyers", open=message.get("open_price", previous.get("open")),
                high=message.get("high_price", previous.get("high")),
                low=message.get("low_price", previous.get("low")),
                volume=message.get("vol_traded_today", previous.get("volume")),
                average_price=message.get("avg_trade_price", previous.get("average_price")),
                bid=message.get("bid_price", previous.get("bid")),
                ask=message.get("ask_price", previous.get("ask")),
                bid_quantity=message.get("bid_size", previous.get("bid_quantity")),
                ask_quantity=message.get("ask_size", previous.get("ask_quantity")),
                last_quantity=message.get("last_traded_qty", previous.get("last_quantity")),
                total_buy_quantity=message.get("tot_buy_qty", previous.get("total_buy_quantity")),
                total_sell_quantity=message.get("tot_sell_qty", previous.get("total_sell_quantity")),
                lower_circuit=message.get("lower_ckt", previous.get("lower_circuit")),
                upper_circuit=message.get("upper_ckt", previous.get("upper_circuit")),
                open_interest=message.get("oi", previous.get("open_interest")))
        except (ValueError, OverflowError, OSError):
            return
        self.connected = True  # A valid tick proves recovery after an SDK error.
        self.last_fyers[symbol] = time.monotonic()
        for key in ("lower_circuit", "upper_circuit"):
            # Some SymbolUpdate frames omit daily limits as zero. Preserve the
            # positive limits fetched from the broker's depth snapshot.
            if not payload.get(key) and previous.get(key):
                payload[key] = previous[key]
        payload.update({key: previous[key] for key in ("depth_as_of",) if key in previous})
        if symbol in self.depth_received:
            payload["depth_as_of"] = self.depth_received[symbol]
        payload.update(self._depth_fields(symbol))
        if previous.get("market_session"):
            payload["market_session"] = previous["market_session"]
        self.fyers_quotes[symbol] = payload
        self._publish(symbol, payload)

    def _index_tick(self, symbol, message):
        """Publish an index observation; indices have no depth or equity fallback."""
        price = number(message.get("ltp"))
        timestamp = number(message.get("exch_feed_time")) or number(message.get("last_traded_time"))
        if price is None or price <= 0 or not timestamp or timestamp > time.time() + 60:
            return
        previous = self.fyers_quotes.get(symbol, {})
        if previous.get("as_of") and datetime.fromtimestamp(timestamp, timezone.utc).isoformat() < previous["as_of"]:
            return
        try:
            payload = quote_payload(symbol, price, message.get("prev_close_price", previous.get("previous_close")),
                                    timestamp, "fyers", open=message.get("open_price", previous.get("open")),
                                    high=message.get("high_price", previous.get("high")),
                                    low=message.get("low_price", previous.get("low")))
        except (ValueError, OverflowError, OSError):
            return
        self.connected = True
        self.fyers_quotes[symbol] = payload
        self._publish(symbol, payload)

    async def subscribe_indices(self, queue):
        """Stream NSE index ticks (no Yahoo polling: the overview snapshot covers gaps)."""
        self.loop = asyncio.get_running_loop()
        added = [s for s in INDEX_STREAM if s not in self.listeners]
        for symbol in INDEX_STREAM:
            self.listeners.setdefault(symbol, set()).add(queue)
        self._start_socket()
        if added and self.connected:
            await self._subscription(added, True)

    async def unsubscribe_indices(self, queue):
        removed = []
        for symbol in INDEX_STREAM:
            listeners = self.listeners.get(symbol, set())
            listeners.discard(queue)
            if not listeners:
                self.listeners.pop(symbol, None)
                removed.append(symbol)
        if removed and self.connected:
            await self._subscription(removed, False)

    def _start_socket(self):
        token = fyers.token()
        if not token or self.socket or time.monotonic() - self._socket_attempt < 60:
            return
        self._socket_attempt = time.monotonic()
        try:
            from fyers_apiv3.FyersWebsocket import data_ws

            def current(callback, *args):
                # SDK reconnects reuse the instance; replaced-token callbacks do not.
                if self.socket is socket:
                    callback(*args)

            def opened():
                self.loop.call_soon_threadsafe(current, self._on_open)

            def closed(*_):
                self.loop.call_soon_threadsafe(current, setattr, self, "connected", False)

            def received(message):
                self.loop.call_soon_threadsafe(current, self._tick, message)

            socket = data_ws.FyersDataSocket(
                access_token=token, log_path="", litemode=False,
                write_to_file=False, reconnect=True, on_connect=opened,
                on_message=received, on_error=closed, on_close=closed)
            self.socket = socket
            self._socket_token = token
            threading.Thread(target=socket.connect, daemon=True, name="fyers-display-feed").start()
        except Exception:
            self.socket = None  # Yahoo fallback stays available.

    def _on_open(self):
        self.connected = True
        if self.listeners:
            asyncio.create_task(self._subscription(list(self.listeners), True))

    async def _subscription(self, symbols, subscribe):
        async with self.socket_lock:
            # Interests may change while waiting for the shared socket lock.
            symbols = list(dict.fromkeys(s for s in symbols if bool(self.listeners.get(s)) == subscribe))
            if symbols and self.socket and self.connected:
                method = self.socket.subscribe if subscribe else self.socket.unsubscribe
                # A crashed SDK symbol-conversion table raises from inside
                # subscribe/unsubscribe; a dead wire must not cascade into a
                # route 500 or a stuck shared-feed release. Recovery recreates
                # the socket; this only contains the error.
                try:
                    await asyncio.to_thread(method, symbols=[f"NSE:{s}" if s.endswith("-INDEX") else f"NSE:{s}-EQ" for s in symbols], data_type="SymbolUpdate")
                    depth_symbols = [s for s in symbols if s in self.deep_symbols and not s.endswith("-INDEX") and bool(self.listeners.get(s)) == subscribe]
                    if depth_symbols:
                        await asyncio.to_thread(method, symbols=[f"NSE:{s}-EQ" for s in depth_symbols], data_type="DepthUpdate")
                except Exception as error:
                    import logging
                    logging.getLogger("quantplus.market").warning(
                        "FYERS subscription send failed: %s", type(error).__name__)

    def _depth_fields(self, symbol):
        raw = self.depth_raw.get(symbol, {})
        levels = []
        for i in range(1, 6):
            level = {"bid": number(raw.get(f"bid_price{i}")), "ask": number(raw.get(f"ask_price{i}")),
                     "bid_quantity": number(raw.get(f"bid_size{i}")), "ask_quantity": number(raw.get(f"ask_size{i}")),
                     "bid_orders": number(raw.get(f"bid_order{i}")), "ask_orders": number(raw.get(f"ask_order{i}"))}
            if (level["bid"] or 0) > 0 or (level["ask"] or 0) > 0:
                levels.append(level)
        return {"depth": levels, "depth_source": "fyers" if levels else None,
                "depth_status": "available" if levels else "unavailable"}

    async def _seed_fyers(self, symbol, token, raw=None):
        raw = raw or await fyers.snapshot(symbol)
        payload = quote_payload(symbol, raw.get("lp"), raw.get("prev_close_price"), raw.get("tt"), "fyers",
            open=raw.get("open_price"), high=raw.get("high_price"), low=raw.get("low_price"), volume=raw.get("volume"),
            average_price=raw.get("atp"), bid=raw.get("bid"), ask=raw.get("ask"))
        try:
            session = await fyers.session()
            if session:
                payload["market_session"] = session
        except Exception:
            pass
        try:
            book = await fyers.depth(symbol) if symbol in self.deep_symbols else {}
            for side, prefix in (("bids", "bid"), ("ask", "ask")):
                for i, row in enumerate(book.get(side, [])[:5], 1):
                    self.depth_raw.setdefault(symbol, {}).update({f"{prefix}_price{i}": row.get("price"),
                        f"{prefix}_size{i}": row.get("volume"), f"{prefix}_order{i}": row.get("ord")})
            payload.update({"lower_circuit": number(book.get("lower_ckt")), "upper_circuit": number(book.get("upper_ckt")),
                            "open_interest": number(book.get("oi")), "total_buy_quantity": number(book.get("totalbuyqty")),
                            "total_sell_quantity": number(book.get("totalsellqty")),
                            "depth_as_of": datetime.now(timezone.utc).isoformat()})
            if number(book.get("atp")) is not None:
                payload["average_price"] = number(book["atp"])
        except Exception:
            pass
        # A newer stream tick takes precedence over the initial REST snapshot.
        current = self.fyers_quotes.get(symbol)
        if current and current.get("as_of", "") > payload["as_of"]:
            limits = {key: payload[key] for key in ("lower_circuit", "upper_circuit") if payload.get(key) and not current.get(key)}
            payload = {**payload, **current, **limits}
        payload.update(self._depth_fields(symbol))
        if fyers.token() != token:
            return  # Ignore a snapshot from credentials replaced during login.
        self.fyers_quotes[symbol] = payload
        self.bootstrap_tokens[symbol] = token
        self._publish(symbol, payload)

    async def refresh_fyers_connection(self, *, only_if_token_changed=False):
        async def refresh():
            async with self.socket_close_lock, self.socket_lock:
                if only_if_token_changed and (not self.socket or fyers.token() == self._socket_token):
                    return
                if self.socket:
                    await asyncio.to_thread(self.socket.close_connection)
                self.socket = None
                self.connected = False
                self._socket_token = ""
                self._socket_attempt = 0
                self.bootstrap_tokens.clear()
                self.snapshot_attempts.clear()
                self.fyers_quotes.clear()
                self.last_fyers.clear()
                self.depth_raw.clear()
                self.depth_received.clear()
                self.history_cache.clear()
                if self.listeners:
                    self._start_socket()

        # A departing stock fallback or cancelled sentiment collection must not
        # interrupt the shared close/reset while the SDK thread is still closing.
        await asyncio.shield(asyncio.create_task(refresh()))

    async def subscribe(self, symbol, queue=None):
        self.loop = asyncio.get_running_loop()
        queue = queue if queue is not None else asyncio.Queue(maxsize=1)
        first = symbol not in self.listeners
        deep = symbol in self.deep_symbols
        self.deep_symbols.add(symbol)
        self.listeners.setdefault(symbol, set()).add(queue)
        self._start_socket()
        if first:
            if self.connected:
                await self._subscription([symbol], True)
            self.tasks[symbol] = asyncio.create_task(self._fallback(symbol))
        elif not deep:
            # A stock page joined an existing board quote subscription.
            self.bootstrap_tokens.pop(symbol, None)
            self.snapshot_attempts.pop(symbol, None)
            if self.connected:
                await self._subscription([symbol], True)
            task = self.tasks.pop(symbol, None)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.tasks[symbol] = asyncio.create_task(self._fallback(symbol))
        if symbol in self.quotes:
            self._publish(symbol, self.quotes[symbol])
        return queue

    async def unsubscribe(self, symbol, queue):
        listeners = self.listeners.get(symbol, set())
        listeners.discard(queue)
        if not listeners:
            self.listeners.pop(symbol, None)
            task = self.tasks.pop(symbol, None)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if self.connected:
                await self._subscription([symbol], False)
            self.deep_symbols.discard(symbol)

    async def subscribe_many(self, symbols, queue=None):
        self.loop = asyncio.get_running_loop()
        queue = queue if queue is not None else asyncio.Queue(maxsize=max(50, len(symbols) * 2))
        added = []
        for symbol in symbols:
            if symbol not in self.listeners:
                added.append(symbol)
            self.listeners.setdefault(symbol, set()).add(queue)
        self._start_socket()
        if added and self.connected:
            await self._subscription(added, True)
        token = fyers.token()
        if added and token:
            try:
                snapshots = await fyers.snapshots(added)
                for symbol, raw in snapshots.items():
                    await self._seed_fyers(symbol, token, raw)
            except Exception:
                pass
        for symbol in added:
            self.tasks[symbol] = asyncio.create_task(self._fallback(symbol))
        for symbol in symbols:
            if symbol in self.quotes:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(self.quotes[symbol])
        return queue

    async def unsubscribe_many(self, symbols, queue):
        removed = []
        tasks = []
        for symbol in symbols:
            listeners = self.listeners.get(symbol, set())
            listeners.discard(queue)
            if not listeners:
                self.listeners.pop(symbol, None)
                removed.append(symbol)
                task = self.tasks.pop(symbol, None)
                if task:
                    task.cancel()
                    tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)
        if removed and self.connected:
            await self._subscription(removed, False)
        self.deep_symbols.difference_update(removed)

    async def _fallback(self, symbol):
        while True:
            token = fyers.token()
            if self.socket and token != self._socket_token:
                await self.refresh_fyers_connection(only_if_token_changed=True)
            self._start_socket()
            if token and self.bootstrap_tokens.get(symbol) != token and time.monotonic() - self.snapshot_attempts.get(symbol, 0) > 60:
                self.snapshot_attempts[symbol] = time.monotonic()
                try:
                    await self._seed_fyers(symbol, token)
                except Exception:
                    pass
            latest = self.fyers_quotes.get(symbol)
            if token and latest:
                try:
                    session = await fyers.session()
                    if session:
                        latest["market_session"] = session
                except Exception:
                    pass
            fresh = (self.connected and time.monotonic() - self.last_fyers.get(symbol, 0) < 30
                     and not self.fyers_quotes.get(symbol, {}).get("stale", True))
            closed_snapshot = token and latest and latest.get("market_session") == "closed"
            if closed_snapshot:
                self._publish(symbol, {**latest, "stale": time.time() - datetime.fromisoformat(latest["as_of"]).timestamp() > 60})
            elif not fresh:
                try:
                    quote = await self.yahoo_quote(symbol)
                    quote.update({"depth": [], "depth_status": "unavailable", "fallback_reason":
                                  "Fyers login required" if not fyers.token() else "Fyers stream unavailable"})
                    self._publish(symbol, quote)
                except Exception:
                    previous = self.quotes.get(symbol)
                    self._publish(symbol, {**(previous or {"symbol": symbol}), "stale": True,
                                           "error": "Market feed unavailable; reconnecting"})
            await asyncio.sleep(max(5 if symbol in self.deep_symbols else 60, settings.YAHOO_QUOTE_REFRESH_SECONDS))

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        if self.socket:
            await asyncio.to_thread(self.socket.close_connection)
        if self.client:
            await self.client.aclose()


market = LiveMarket()
