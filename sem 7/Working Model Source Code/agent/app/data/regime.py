"""VIX regime classifier: PIT-safe CALM / ELEVATED / STRESSED for the M3 gate.

Data path: India VIX (^INDIAVIX) pulled live via YFinanceProvider (verified
2026-09-20: yfinance serves daily ^INDIAVIX history back to at least 2022).
No realized-vol proxy is used — direct VIX was available and reliable.

PIT discipline (same as exhaustion_features()): the trailing percentile
distribution is computed ONLY from bars strictly before asof_idx; the current
bar's value is ranked against that history, never included in it.

History depth note: YFinanceProvider serves a 180-day span for 1d bars
(~126 trading bars), so the trailing window below is the last min(lookback,
available) bars — typically ~125, always >= MIN_HISTORY_BARS or we default.
Cutoffs (50th/85th) were validated against actual ^INDIAVIX 2022-2025 data:
across the 48 v5/v5.1 eval as_of dates they split CALM=29 / ELEVATED=11 /
STRESSED=8 — no degenerate bucket (election-spike May-Jun 2024 and Jan/Apr/May
2025 tapes land STRESSED as expected).

Conservative defaults: insufficient history (<60 bars), missing data, or any
fetch failure -> "CALM" (never gate on data we do not have). regime_at() is
total: it never raises.
"""
from __future__ import annotations
from datetime import datetime
import pandas as pd

from app.data.yfinance_provider import YFinanceProvider

VIX_TICKER = "^INDIAVIX"
MIN_HISTORY_BARS = 60
CALM_MAX_PCT = 50.0
STRESSED_MIN_PCT = 85.0


def classify_regime(vix: pd.Series, asof_idx: int, lookback: int = 252) -> str:
    """Rank the asof bar's VIX against its own trailing history.

    pct = % of trailing bars (strictly before asof_idx, up to `lookback` of
    them) with VIX <= current value. CALM below CALM_MAX_PCT, STRESSED at or
    above STRESSED_MIN_PCT, ELEVATED between. Fewer than MIN_HISTORY_BARS of
    trailing history -> "CALM" (documented conservative default).
    """
    vals = vix.dropna()
    if asof_idx < 0 or asof_idx >= len(vals):
        return "CALM"
    current = float(vals.iloc[asof_idx])
    hist = vals.iloc[max(0, asof_idx - lookback):asof_idx]
    if len(hist) < MIN_HISTORY_BARS:
        return "CALM"
    # Strict <: a flat VIX stretch ranks at 0 (CALM), never at 100. For
    # continuous data <= vs < is immaterial; for ties only < is safe.
    pct = float((hist < current).mean() * 100)
    if pct >= STRESSED_MIN_PCT:
        return "STRESSED"
    if pct >= CALM_MAX_PCT:
        return "ELEVATED"
    return "CALM"


def regime_at(as_of: datetime) -> str:
    """Live convenience: fetch ^INDIAVIX history PIT-safe, classify at as_of.

    Total function: any fetch/parse problem returns "CALM" (never gate blind).
    """
    try:
        df = YFinanceProvider().ohlcv(VIX_TICKER, as_of, "1d", lookback=400)
        closes = df["Close"].dropna()
        if not isinstance(closes, pd.Series) or len(closes) < 2:
            return "CALM"
        return classify_regime(closes, len(closes) - 1)
    except Exception:
        return "CALM"


# ---------------------------------------------------------------------------
# Market-trend classifier: the index's OWN trend, for a symmetric counter-trend
# guardrail. Motivation (see data/baseline_analysis.json): the live agent's
# directional SELECTION has negative skill vs a constant-rule baseline on both
# the bull (v5-2025) and bear (v3rd-2026) sets — it underperforms "always long"
# in up tapes and "always short" in down tapes because it repeatedly takes
# positions against the market's own trend (buying selloffs / selling rallies).
# This is a risk rule, not a signal: "do not fight the index trend."
# ---------------------------------------------------------------------------
TREND_TICKER = "^NSEI"
MIN_TREND_BARS = 60


def classify_trend(closes: pd.Series, asof_idx: int, min_bars: int = MIN_TREND_BARS) -> str:
    """Classify the index's trend at asof_idx: UP / DOWN / RANGE / UNKNOWN.

    PIT discipline identical to classify_regime: only bars up to and INCLUDING
    asof_idx are read (the asof bar is already available after its 15-min delay
    via the provider), never a future bar. A trend is "confirmed" only when the
    price AND the short average sit on the same side of the longer average, so a
    single spike cannot flip the regime. Fewer than min_bars of history, a bad
    index, or an out-of-range index -> "UNKNOWN" (never gate blind).

    Note: the provider serves a 180-day span for 1d bars (~126 trading bars),
    so a 50-bar average is the effective long lookback (200 is unavailable).
    """
    vals = closes.dropna()
    if asof_idx < 0 or asof_idx >= len(vals):
        return "UNKNOWN"
    upto = vals.iloc[: asof_idx + 1]
    if len(upto) < min_bars:
        return "UNKNOWN"
    close = float(upto.iloc[-1])
    ma20 = float(upto.tail(20).mean())
    ma50 = float(upto.tail(50).mean())
    if close < ma50 and ma20 < ma50:
        return "DOWN"
    if close > ma50 and ma20 > ma50:
        return "UP"
    return "RANGE"


def market_trend_at(as_of: datetime) -> str:
    """Live convenience: index trend (^NSEI) at as_of. Total function — any
    fetch/parse problem returns "UNKNOWN" (never gate on missing data).
    """
    try:
        df = YFinanceProvider().ohlcv(TREND_TICKER, as_of, "1d", lookback=400)
        closes = df["Close"].dropna()
        if not isinstance(closes, pd.Series) or len(closes) < 2:
            return "UNKNOWN"
        return classify_trend(closes, len(closes) - 1)
    except Exception:
        return "UNKNOWN"
