"""Deterministic, PIT-safe volatility features (standalone; no app/ imports, no app/ changes).

Rule shapes copied from the agent-service patterns with attribution:
- percentile ranking: strict-`<` against strictly-prior trailing history
  (same as app/data/regime.py classify_regime: flat stretches rank 0, ties safe).
- flush/blowoff flags: same construction as app/agents/features.py
  exhaustion_features (ticker-own |ret_5d| 80th-pct over strictly-prior bars,
  1% floor, 8.0% fallback under 60 bars).

Every function takes positional integer `i` = forecast bar and uses rows
<= i for inputs. Forward quantities (labels) live in targets.py, never here.
"""
from __future__ import annotations
import math
import pandas as pd

ANN = 252.0
RV_WIN = 20
HIST = 252
FALLBACK_THRESHOLD = 8.0


def log_returns(close: pd.Series) -> pd.Series:
    return (close / close.shift(1)).apply(math.log)


def realized_vol20(close: pd.Series) -> pd.Series:
    """Annualized trailing 20d std of log returns. rv[i] uses bars i-19..i (via returns)."""
    r = log_returns(close)
    return r.rolling(RV_WIN).std() * math.sqrt(ANN)


def trailing_median252(rv: pd.Series) -> pd.Series:
    return rv.rolling(HIST).median()


def vol_percentile_rank(rv: pd.Series, i: int, lookback: int = HIST) -> float:
    """Percentile of rv[i] within trailing `lookback` values STRICTLY before i.

    strict-`<`: pct = mean(hist < current) * 100 (regime.py convention).
    Returns 50.0 (neutral) when fewer than 60 bars of history exist.
    """
    if i < 0 or i >= len(rv) or pd.isna(rv.iloc[i]):
        return 50.0
    hist = rv.iloc[max(0, i - lookback):i].dropna()
    if len(hist) < 60:
        return 50.0
    return float((hist < rv.iloc[i]).mean() * 100.0)


def vix_level(vix_close: pd.Series, i: int) -> float:
    return float(vix_close.iloc[i])


def vix_5d_slope(vix_close: pd.Series, i: int) -> float:
    """(VIX_i / VIX_{i-5} - 1). NaN when insufficient history."""
    if i < 5 or i >= len(vix_close):
        return float("nan")
    a, b = vix_close.iloc[i], vix_close.iloc[i - 5]
    if pd.isna(a) or pd.isna(b) or b == 0:
        return float("nan")
    return float(a / b - 1.0)


def _exhaustion_threshold(close: pd.Series, i: int, lookback_pct: int = 252) -> float:
    """Ticker-own |ret_5d| 80th-pct over bars STRICTLY before i (exhaustion_features shape)."""
    hist = close.iloc[max(0, i - lookback_pct):i]
    if len(hist) >= 60:
        r5 = hist.pct_change(5).abs() * 100.0
        return max(float(r5.quantile(0.80)), 1.0)
    return FALLBACK_THRESHOLD


def _flag_at(close: pd.Series, i: int) -> tuple[bool, bool]:
    """(flush, blowoff) at bar i, PIT-safe. Needs i>=5."""
    if i < 5 or i >= len(close):
        return False, False
    c, c5 = float(close.iloc[i]), float(close.iloc[max(0, i - 5)])
    ret5 = (c - c5) / c5 * 100.0
    thr = _exhaustion_threshold(close, i)
    return bool(ret5 <= -thr), bool(ret5 >= thr)


def recent_extreme_move_freq(close: pd.Series, i: int, window: int = 20) -> int:
    """Count of bars with flush OR blowoff in bars max(0,i-window+1)..i (each PIT-safe)."""
    n = 0
    for j in range(max(0, i - window + 1), i + 1):
        f, b = _flag_at(close, j)
        if f or b:
            n += 1
    return n


def vix_regime_bucket(vix_close: pd.Series, i: int, lookback: int = 252) -> str:
    """CALM <50th / ELEVATED 50-85th / STRESSED >=85th, strict-<, <60 bars -> CALM."""
    if i < 0 or i >= len(vix_close) or pd.isna(vix_close.iloc[i]):
        return "CALM"
    hist = vix_close.iloc[max(0, i - lookback):i].dropna()
    if len(hist) < 60:
        return "CALM"
    pct = float((hist < vix_close.iloc[i]).mean() * 100.0)
    if pct >= 85.0:
        return "STRESSED"
    if pct >= 50.0:
        return "ELEVATED"
    return "CALM"
