"""Provider protocols + PIT helpers. Agents depend on protocols, not yfinance/gnews."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Protocol
import pandas as pd

YF_DELAY_MIN = 15  # Yahoo quote delay guard

class MarketDataProvider(Protocol):
    name: str
    def ohlcv(self, instrument: str, as_of: datetime, interval: str = "1d", lookback: int = 120) -> pd.DataFrame: ...

class NewsItem(dict):
    pass

class NewsProvider(Protocol):
    name: str
    def headlines(self, query: str, as_of: datetime, max_items: int = 10) -> list[dict]: ...

def assert_pit(available_at: datetime, as_of: datetime):
    a = available_at if available_at.tzinfo else available_at.replace(tzinfo=timezone.utc)
    b = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    if a > b:
        raise ValueError(f"PIT breach: available_at={a} > as_of={b}")

ROUNDTRIP_COST = 0.0021  # ~0.21% Indian round-trip

# Vendor data-status taxonomy (Day 2 T2.4, NEW_PLAN — "unavailable, not absent"):
# DATA_OK = vendor succeeded, values usable.
# DATA_UNAVAILABLE = this vendor failed (says nothing about the symbol).
# NO_DATA = all vendors agree: invalid/delisted/stale. Devil must discard
#   UNAVAILABLE, never treat it as bearish evidence.
DATA_OK = "DATA_OK"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
NO_DATA = "NO_DATA"

def apply_cost(notional: float) -> float:
    return notional * (1 - ROUNDTRIP_COST)
