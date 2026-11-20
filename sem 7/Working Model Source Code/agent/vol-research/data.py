"""Data access for vol-research (standalone; yfinance + disk cache, no app/ imports)."""
from __future__ import annotations
import os
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(CACHE_DIR, exist_ok=True)


def _download(symbol: str, start: str = "2007-01-01", end: str = "2026-01-01") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, interval="1d",
                     auto_adjust=False, progress=False, prepost=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.sort_index()


def load(symbol: str) -> pd.DataFrame:
    key = os.path.join(CACHE_DIR, symbol.replace("^", "").replace(".", "_") + "_1d_full.csv")
    if os.path.exists(key):
        df = pd.read_csv(key, index_col=0, parse_dates=True)
    else:
        df = _download(symbol)
        df.to_csv(key)
    return df


def load_aligned() -> pd.DataFrame:
    """NIFTY-indexed frame with VIX reindexed onto it (NaN where VIX unavailable)."""
    nsei = load("^NSEI")
    vix = load("^INDIAVIX")
    out = pd.DataFrame({"Close": nsei["Close"]})
    out["VIX"] = vix["Close"].reindex(out.index)
    return out.dropna(subset=["Close"])
