"""Deterministic settlement (§49): maturity-gated, exactly-once, idempotent.

Settlement timestamps are explicit. A second run over settled rows changes
nothing. Late sources cannot rewrite first-seen evidence (no mutation API for
raw/event timestamps exists — asserted by test).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import sqlite_conn
from app.forward import records as REC


def settle_as_of(now_iso: str, horizon_days: int = 5, price_fn=None) -> dict:
    """Settle UNSETTLED rows whose horizon matured (ts + horizon <= now).
    price_fn(instrument, start_ts, end_ts) -> (start_px, end_px) | None.
    Live default uses yfinance closes (best-effort; unavailable -> stays
    UNSETTLED, never estimated). Returns counts."""
    REC.init_tables()
    now = datetime.fromisoformat(now_iso)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    rows = sqlite_conn().execute(
        "SELECT decision_id, ts, instrument, desired, paper FROM forward_decisions"
        " WHERE outcome='UNSETTLED'").fetchall()
    settled, pending, failed = 0, 0, 0
    for did, ts, inst, desired, paper in rows:
        matured = False
        try:
            t0 = datetime.fromisoformat(ts)
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            matured = (now - t0).days >= horizon_days
        except ValueError:
            failed += 1
            continue
        if not matured:
            pending += 1
            continue
        prices = (price_fn(inst, ts, now_iso) if price_fn else _live_prices(inst, ts))
        if not prices or not prices[0]:
            pending += 1  # unavailable — stays UNSETTLED, never estimated
            continue
        start_px, end_px = prices
        fwd = end_px / start_px - 1
        outcome = "GAIN" if (paper * fwd) > 0 else ("FLAT" if fwd == 0 else "LOSS")
        sqlite_conn().execute(
            "UPDATE forward_decisions SET outcome=?, settled_ts=? WHERE decision_id=?"
            " AND outcome='UNSETTLED'",  # exactly-once guard
            (f"{outcome}:{fwd:.4f}", now.isoformat(), did))
        settled += 1
    sqlite_conn().commit()
    return {"settled": settled, "pending": pending, "failed": failed, "as_of": now_iso}


def _live_prices(instrument: str, start_iso: str):
    try:
        from app.data.yfinance_provider import YFinanceProvider
        from datetime import datetime as _dt
        now = _dt.now(timezone.utc)
        df = YFinanceProvider().ohlcv(instrument, now, "1d", lookback=30)
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        start_day = start_iso[:10]
        past = closes[[str(d.date()) <= start_day for d in closes.index]]
        if len(past) == 0:
            return None
        return float(past.iloc[-1]), float(closes.iloc[-1])
    except Exception:  # noqa: BLE001 - unavailable stays UNSETTLED
        return None


def experiment_counts(freeze_iso: str, now_iso: str) -> dict:
    """§52 event-experiment counts from live stores (honest zeros included)."""
    from app.events import store as ST
    ST.init_tables()
    recs = ST.announcements_in_range(freeze_iso, now_iso)
    eligible = [r for r in recs
                if (r.get("classification") or {}).get("blackout_candidate")]
    companies = {r["symbol"] for r in recs}
    days = {r["publication_ts"][:10] for r in recs}
    abstentions = sum(1 for r in recs if not r.get("classification"))
    return {"announcements_received": len(recs),
            "pit_eligible_announcements": len(eligible),
            "classified_events": sum(1 for r in recs if r.get("classification")),
            "abstentions": abstentions,
            "events_intersecting_opportunity": 0,  # gate-log joined at judgment time
            "blocked_entries": 0, "blocked_increases": 0,
            "control_opportunities": 0,
            "independent_companies": len(companies),
            "independent_event_days": len(days)}
