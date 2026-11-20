"""Universe tiers: NIFTY50 (frozen) / NIFTY500 / SME.

Day 1 T1.3 (NEW_PLAN): NIFTY-500 + SME target needs explicit tiers so Monday
ships tiered: NIFTY-50 fully validated, 500 backtested, SME paper-only.

Rules:
- NIFTY50_FROZEN: the 37 names in app/core/trend_core.py UNIVERSE (frozen rule).
  Import lives there; this module references it, never duplicates it.
- NIFTY500: broad list supplied via data/nifty500.txt (one ticker per line,
  `.NS` suffix). Absent file => explicit error, never silent fallback to NIFTY50.
- SME: same file mechanism (data/sme.txt), gated by illiquidity filter:
  ADT20d > Rs.50L notional AND close > Rs.20 AND no upper-circuit 5d streak.
  SME backtests are paper-only with wide-spread disclosure.

Position caps (enforced by core v3, documented here):
- NIFTY50 name: MAX 10% (existing MAX_POSITION_PCT)
- NIFTY500 non-50 name: MAX 5%
- SME name: MAX 3%, sector cap 25% (core v3)
"""
from __future__ import annotations

import os

NIFTY500_LIST_PATH = "data/nifty500.txt"
SME_LIST_PATH = "data/sme.txt"

SME_MIN_ADT_NOTIONAL = 5_000_00 * 10  # Rs.50L (5_000_000)
SME_MIN_PRICE = 20.0
SME_MAX_POSITION_PCT = 0.03
NIFTY500_NON50_MAX_POSITION_PCT = 0.05


def load_list(path: str) -> list[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"universe list missing: {path} — supply one ticker per line (.NS). "
            "No silent fallback.")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            t = line.strip().upper()
            if t and not t.startswith("#"):
                out.append(t)
    return sorted(set(out))


def nifty50_frozen() -> list[str]:
    from app.core.trend_core import UNIVERSE
    return list(UNIVERSE)


def nifty500() -> list[str]:
    return load_list(NIFTY500_LIST_PATH)


def sme() -> list[str]:
    return load_list(SME_LIST_PATH)


def sme_liquid(df, lookback: int = 20) -> bool:
    """Illiquidity gate for one SME name. df: OHLCV with Close/Volume, PIT-tail already.

    Returns False (exclude) when: too cheap, too thin, or locked in upper circuits.
    Upper-circuit proxy (no circuit data on Yahoo): 5 consecutive >+19% daily gains
    with tiny intraday range is treated as locked — excluded as untradeable.
    """
    try:
        closes = df["Close"].dropna().tail(lookback)
        vols = df["Volume"].dropna().tail(lookback)
        if len(closes) < lookback or len(vols) < lookback:
            return False
        last = float(closes.iloc[-1])
        if last < SME_MIN_PRICE:
            return False
        adt = float((closes * vols).tail(lookback).mean())
        if adt < SME_MIN_ADT_NOTIONAL:
            return False
        rets = [(closes.iloc[i] / closes.iloc[i - 1] - 1) for i in range(1, len(closes))]
        if len(rets) >= 5 and all(r > 0.19 for r in rets[-5:]):
            return False
        return True
    except Exception:
        return False
