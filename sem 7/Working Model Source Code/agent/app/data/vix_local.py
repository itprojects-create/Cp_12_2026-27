"""Local India-VIX panel (prereg_model_data_wiring.md Step 2b).

Deterministic regime input: exact-date join on EOD levels with the same T+1
discipline (row date < as_of date). Missing/stale file -> None (caller falls
back to yfinance, logged there). Never raises on data problems.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache

DEFAULT_VIX_PATH = (
    os.environ.get("VIX_CSV_PATH")
    or r"D:\Model\data\raw\india_vix.csv"
)
STALE_AFTER_DAYS = 30


def _asof_date(as_of: datetime) -> str:
    a = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    return a.date().isoformat()


@lru_cache(maxsize=4)
def _load(path: str):
    import pandas as pd
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.sort_values("date").reset_index(drop=True)


def history(as_of: datetime, lookback: int = 400,
            path: str | None = None) -> list[float] | None:
    """Trailing vix_close strictly before as_of date (longest `lookback`).
    None when the file is missing, stale (>30d before as_of), or unparseable."""
    try:
        df = _load(path or DEFAULT_VIX_PATH)
    except Exception:
        return None
    day = _asof_date(as_of)
    sub = df[df["date"] < day]
    if sub.empty:
        return None
    try:
        last_day = sub["date"].iloc[-1]
        age = (datetime.fromisoformat(day) - datetime.fromisoformat(last_day)).days
    except ValueError:
        return None
    if age > STALE_AFTER_DAYS:
        return None
    return [float(x) for x in sub["vix_close"].tail(lookback).tolist()]


def close_at(as_of: datetime, path: str | None = None) -> float | None:
    h = history(as_of, lookback=1, path=path)
    return h[-1] if h else None
