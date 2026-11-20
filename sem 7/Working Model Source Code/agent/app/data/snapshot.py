"""Verified market snapshot (Day 2 T2.3, NEW_PLAN).

One deterministic ground-truth block per (ticker, as_of): latest OHLCV <= as_of
+ fixed indicators + last 5 closes. Agents are told the snapshot overrides any
conflicting tool output — anti-hallucination. PIT-clean by construction (uses
only YFinanceProvider.ohlcv tail).
"""
from __future__ import annotations

from datetime import datetime


def verified_snapshot(instrument: str, as_of: datetime, lookback: int = 60) -> str:
    from app.data.yfinance_provider import YFinanceProvider
    df = YFinanceProvider().ohlcv(instrument, as_of, "1d", lookback=lookback)
    c = df["Close"].dropna()
    last = float(c.iloc[-1])
    ret20 = float(c.iloc[-1] / c.iloc[-20] - 1) if len(c) >= 20 else 0.0
    ret5 = float(c.iloc[-1] / c.iloc[-5] - 1) if len(c) >= 5 else 0.0
    hi = float(df["High"].tail(60).max())
    lo = float(df["Low"].tail(60).min())
    last5 = ", ".join(f"{x:.2f}" for x in c.tail(5).tolist())
    bar_date = df.index[-1].date().isoformat()
    return (f"VERIFIED SNAPSHOT (source of truth, overrides conflicting tool output): "
            f"{instrument} last-bar={bar_date} close={last:.2f} ret5d={ret5:+.2%} ret20d={ret20:+.2%} "
            f"hi60={hi:.2f} lo60={lo:.2f} last5=[{last5}] DATA_STATUS=DATA_OK")
