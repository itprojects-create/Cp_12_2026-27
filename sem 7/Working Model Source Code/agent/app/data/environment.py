"""Honest measurement environment (NEWW_PLAN Day 1, prereg data/prereg_day1_environment.md).

Deterministic, zero tokens. Changes MEASUREMENT only — selection logic in
app/core/* is untouched. Unknown tiers raise (never silent); missing calendar
raises (never silent empty).
"""
from __future__ import annotations

import json
import os

# Per-side costs by segment (prereg table). SME 1.5% reflects 1-3% spreads.
TIER_COST_PER_SIDE = {
    "nifty50": 0.00105,
    "nifty500": 0.0020,
    "sme": 0.0150,
}

# NSE equity price bands. Exact per-name band feed deferred to NSE archives;
# estimate_band() maps 20d realized extremes UP to the next band (conservative:
# assumes tighter bands than reality only when history is calm — documented).
BANDS = (0.02, 0.05, 0.10, 0.20)


def cost_per_side(tier: str) -> float:
    try:
        return TIER_COST_PER_SIDE[tier]
    except KeyError:
        raise ValueError(f"unknown segment tier {tier!r} — no silent cost default") from None


def estimate_band(closes_20d: list[float]) -> float:
    """Smallest NSE band containing the 20d max |daily| move (proxy)."""
    if len(closes_20d) < 2:
        return BANDS[-1]
    worst = 0.0
    for i in range(1, len(closes_20d)):
        prev = closes_20d[i - 1]
        if prev and prev > 0:
            worst = max(worst, abs(closes_20d[i] / prev - 1))
    for b in BANDS:
        if worst < b:
            return b
    return BANDS[-1]


def is_locked(o: float, h: float, l: float, c: float, band: float) -> bool:
    """Limit-locked bar: pinned at the band edge with (near-)zero range.

    Conservative direction: treated as unfillable (we are always assumed to be
    on the wrong side of the lock). Caller defers the fill, books no cost.
    """
    if not o or o <= 0:
        return False
    pinned = abs(c / o - 1) >= band - 0.001
    frozen = (h - l) / o < 0.005 if o else False
    return bool(pinned and frozen)


def load_calendar(path: str = "data/event_calendar.json") -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"event calendar missing: {path} — no silent empty calendar.")
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def event_gross_multiplier(date_iso: str, calendar: dict) -> float:
    """0.5 inside any event [t-pre, t+post] window, else 1.0. Date compare is
    lexicographic on ISO YYYY-MM-DD (valid for fixed-width dates)."""
    d = date_iso[:10]
    for ev in calendar.get("events", []):
        if _in_window(d, ev["date"], ev.get("pre", 2), ev.get("post", 1)):
            return 0.5
    return 1.0


def _in_window(d: str, center: str, pre: int, post: int) -> bool:
    from datetime import date, timedelta
    try:
        dd = date.fromisoformat(d)
        cc = date.fromisoformat(center)
    except ValueError:
        return False
    delta = (dd - cc).days
    return -pre <= delta <= post


def token_spend_rupees(tokens: int, rupees_per_1k: float) -> float:
    if tokens < 0 or rupees_per_1k < 0:
        raise ValueError("tokens and rate must be non-negative")
    return tokens / 1000.0 * rupees_per_1k


def total_inference_tokens() -> int:
    """Cumulative tokens from the gateway ledger (usage_daily)."""
    from app.db import sqlite_conn
    row = sqlite_conn().execute("SELECT COALESCE(SUM(tokens),0) FROM usage_daily").fetchone()
    return int(row[0]) if row else 0
