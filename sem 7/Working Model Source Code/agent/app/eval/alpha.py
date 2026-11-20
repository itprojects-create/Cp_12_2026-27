"""Alpha vs regional benchmark (Day 5, NEW_PLAN).

Benchmark map: .NS/.BO => ^NSEI (NIFTY), else SPY. Alpha measured over the
same holding window as forward_return (20 trading days). Failures return None
(pending), never fabricate.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def resolve_benchmark(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return "^NSEI"
    return "SPY"


def alpha_return(ticker: str, as_of: datetime, horizon: int = 20) -> float | None:
    """Raw-minus-benchmark return over horizon trading days. None if unsettled."""
    try:
        import yfinance as yf
        bench = resolve_benchmark(ticker)
        start = (as_of - timedelta(days=7)).date().isoformat()
        end = (as_of + timedelta(days=horizon + 30)).date().isoformat()
        df_s = yf.download(ticker, start=start, end=end, interval="1d",
                           auto_adjust=True, progress=False)
        df_b = yf.download(bench, start=start, end=end, interval="1d",
                           auto_adjust=True, progress=False)
        for df in (df_s, df_b):
            if isinstance(df.columns, __import__("pandas").MultiIndex):
                df.columns = [c[0] for c in df.columns]
        cs = df_s["Close"].dropna()
        cb = df_b["Close"].dropna()
        if getattr(cs.index, "tz", None) is None:
            cs.index = cs.index.tz_localize("UTC")
        if getattr(cb.index, "tz", None) is None:
            cb.index = cb.index.tz_localize("UTC")
        a = as_of if as_of.tzinfo else as_of.replace(tzinfo=__import__("datetime").timezone.utc)
        posts = cs[cs.index > a]
        if len(posts) < horizon + 1:
            return None
        entry, exit_ = posts.index[0], posts.index[horizon]
        raw = float(posts.iloc[horizon] / posts.iloc[0] - 1)
        be, bx = cb.asof(entry), cb.asof(exit_)
        if be is None or bx is None or be <= 0:
            return None
        return raw - float((bx - be) / be)
    except Exception:
        return None
