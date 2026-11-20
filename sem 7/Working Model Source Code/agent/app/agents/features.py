"""Deterministic market features: compute numbers in code, let the LLM interpret them.

Rationale: pasting 20 raw OHLCV rows (~1300 tokens) makes reasoning models burn their
whole token budget 'thinking' about the table and emit nothing (finish=length, empty
content). A compact feature block (~300 tokens) fixes reliability AND cost.
"""
from __future__ import annotations
import pandas as pd

def describe(df: pd.DataFrame, interval: str = "1d") -> str:
    closes = df["Close"].dropna()
    last = float(closes.iloc[-1])
    sma20 = float(closes.tail(20).mean())
    ret5 = float(closes.iloc[-1] / closes.iloc[-6] - 1) if len(closes) >= 6 else 0.0
    ret20 = float(closes.iloc[-1] / closes.iloc[-21] - 1) if len(closes) >= 21 else 0.0
    hi20 = float(df["High"].tail(20).max())
    lo20 = float(df["Low"].tail(20).min())
    avgvol = float(df["Volume"].tail(20).mean())
    lastvol = float(df["Volume"].iloc[-1])
    # up/down days last 10
    chg = closes.diff().tail(10).dropna()
    up = int((chg > 0).sum())
    closes_csv = ",".join(f"{x:.2f}" for x in closes.tail(20).tolist())
    first_ts = df.index[0].date().isoformat()
    last_ts = df.index[-1].date().isoformat()
    hi60 = float(df["High"].tail(60).max())
    breakout_up = last >= hi60 * 0.995
    return (f"range={first_ts}..{last_ts} interval={interval} n={len(closes)}\n"
            f"last={last:.2f} sma20={sma20:.2f} vs_sma={(last/sma20-1):+.2%}\n"
            f"ret5d={ret5:+.2%} ret20d={ret20:+.2%} hi20={hi20:.2f} lo20={lo20:.2f}\n"
            f"vol_last={lastvol:,.0f} vol_avg20={avgvol:,.0f} volx={lastvol/avgvol if avgvol else 0:.2f} "
            f"up_days_10={up}\n"
            f"breakout20d={'YES' if breakout_up else 'no'} dist_hi60={(last/hi60-1):+.2%}\n"
            f"closes20=[{closes_csv}]")

def exhaustion_features(df: pd.DataFrame, asof_idx: int, lookback_pct_window: int = 252) -> dict:
    """Exhaustion gauge: flush (sold-out bounce risk) vs blowoff (exhausted top).

    All lookbacks use bars up to and including asof_idx — no lookahead.
    Thresholds derive from this ticker's OWN distribution of 5-day returns
    (80th percentile of |ret_5d| — re-tuned from 90th in the M2 rehab round:
    corrected re-measurement on 48 real sessions showed 25% fire at 80th vs
    8% at 90th, and the history-window fix made the real branch the norm),
    computed ONLY over bars strictly before asof_idx. Falls back to 8.0%
    with <60 bars of history.
    Column convention matches provider frames: Close/High/Low.
    """
    window = df.iloc[max(0, asof_idx - 19):asof_idx + 1]
    low_20 = float(window["Low"].min())
    high_20 = float(window["High"].max())
    close = float(df.iloc[asof_idx]["Close"])
    close_5d_ago = float(df.iloc[max(0, asof_idx - 5)]["Close"])
    ret_5d_pct = (close - close_5d_ago) / close_5d_ago * 100

    hist_start = max(0, asof_idx - lookback_pct_window)
    hist = df.iloc[hist_start:asof_idx]
    if len(hist) >= 60:
        hist_ret5 = hist["Close"].pct_change(5).abs() * 100
        # Floor at 1%: a zero-volatility history must not yield a 0% threshold
        # that flags every flat market as exhausted.
        threshold = max(float(hist_ret5.quantile(0.80)), 1.0)
    else:
        threshold = 8.0

    return {
        "dist_from_20d_low_pct": round((close - low_20) / low_20 * 100, 2),
        "dist_from_20d_high_pct": round((close - high_20) / high_20 * 100, 2),
        "ret_5d_pct": round(ret_5d_pct, 2),
        "exhaustion_threshold_pct": round(threshold, 2),
        "flush_flag": bool(ret_5d_pct <= -threshold),
        "blowoff_flag": bool(ret_5d_pct >= threshold),
    }

def exhaustion_line(df: pd.DataFrame) -> str:
    """One-line injection for analyst prompts: features at the last bar."""
    return format_exhaustion(exhaustion_features(df, len(df) - 1))

def format_exhaustion(e: dict) -> str:
    """Render a precomputed exhaustion dict (same object the Technical saw)."""
    state = ("FLUSH (sold-out bounce risk)" if e["flush_flag"] else
             "BLOWOFF (exhausted top risk)" if e["blowoff_flag"] else "no exhaustion signal")
    # Field names match the keys the Technical prompt names and are unique within its
    # input, so the grounding validator can verify citations of them.
    risk = int(e["flush_flag"] or e["blowoff_flag"])
    return (f"exhaustion: dist_from_20d_low_pct={e['dist_from_20d_low_pct']:+.2f}% "
            f"dist_from_20d_high_pct={e['dist_from_20d_high_pct']:+.2f}% "
            f"ret_5d_pct={e['ret_5d_pct']:+.2f}% "
            f"exhaustion_threshold_pct={e['exhaustion_threshold_pct']:.2f}% "
            f"flush_flag={int(e['flush_flag'])} blowoff_flag={int(e['blowoff_flag'])} "
            f"exhaustion_reversal_risk={risk} -> {state}")
