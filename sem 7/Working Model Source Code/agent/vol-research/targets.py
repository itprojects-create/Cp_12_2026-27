"""Forward (label) quantities only. Uses bars strictly AFTER the forecast bar.
Never imported by feature code; used by the backtest to score predictions.
"""
from __future__ import annotations
import math
import pandas as pd
from features import log_returns, ANN


def fwd_realized_vol(close: pd.Series, i: int, horizon: int) -> float:
    """Annualized std of log returns over bars i+1..i+horizon. NaN if unavailable."""
    r = log_returns(close)
    seg = r.iloc[i + 1:i + 1 + horizon].dropna()
    if len(seg) < horizon:
        return float("nan")
    return float(seg.std() * math.sqrt(ANN))


def binary_label(fwd_rv: float, trailing_median: float) -> str:
    return "ABOVE" if fwd_rv > trailing_median else "BELOW"
