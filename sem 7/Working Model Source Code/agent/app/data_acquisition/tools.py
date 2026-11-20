"""Curated research-agent data tools (§§94–95).

Agents never browse sources: deterministic filters select, caps bound context,
every response carries provenance + PIT status. Row caps keep LLM context small
(code selects relevant rows; the LLM reads the selection, never the lake).
"""
from __future__ import annotations

MAX_ROWS = 50


def _prov(source: str, dataset: str, pit_status: str, extra: dict | None = None) -> dict:
    return {"source": source, "dataset": dataset, "pit_status": pit_status,
            **(extra or {})}


def query_announcements(symbol: str, start: str, end: str,
                        limit: int = MAX_ROWS) -> dict:
    """Classified announcements for one symbol in window (newest last, capped)."""
    from app.events import store as ST
    rows = [r for r in ST.announcements_in_range(start, end)
            if r["symbol"] == symbol.upper()][:limit]
    return {"rows": rows, "truncated": len(rows) == limit,
            "provenance": _prov("event-store", "announcements",
                                "VERIFIED" if rows else "UNKNOWN",
                                {"taxonomy_pinned": True})}


def query_market_data(symbol: str, start: str, end: str,
                      limit: int = MAX_ROWS) -> dict:
    """Normalized EOD rows for one symbol (capped, newest last)."""
    from app.data_acquisition import parquet as PQ
    import datetime as _dt
    out, months = [], set()
    d0 = _dt.date.fromisoformat(start[:10])
    d1 = _dt.date.fromisoformat(end[:10])
    cur = _dt.date(d0.year, d0.month, 1)
    while cur <= d1 and len(months) < 4:
        months.add(cur.strftime("%Y-%m"))
        cur = _dt.date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
    for mm in sorted(months):
        try:
            df = PQ.read_month("equity-eod", mm)
        except Exception:  # noqa: BLE001 - missing pyarrow/month -> abstain slice
            continue
        if df.empty:
            continue
        sel = df[(df.symbol == symbol.upper())
                 & (df.trade_date >= start[:10]) & (df.trade_date <= end[:10])]
        out.extend(sel.to_dict(orient="records"))
        if len(out) >= limit:
            break
    rows = out[:limit]
    return {"rows": rows, "truncated": len(out) >= limit,
            "provenance": _prov("NSE-archives", "equity-eod",
                                "VERIFIED" if rows else "UNKNOWN")}


def query_deals(symbol: str, start: str, end: str, limit: int = MAX_ROWS) -> dict:
    from app.data_acquisition import parquet as PQ
    try:
        frames = []
        for mm in _months_between(start, end, cap=4):
            df = PQ.read_month("bulk-block-deals", mm)
            if not df.empty:
                frames.append(df[(df.symbol == symbol.upper())
                                 & (df.trade_date >= start[:10])
                                 & (df.trade_date <= end[:10])])
    except Exception:  # noqa: BLE001
        return {"rows": [], "truncated": False,
                "provenance": _prov("NSE-archives", "bulk-block-deals", "UNKNOWN")}
    import pandas as _pd
    rows = (_pd.concat(frames).to_dict(orient="records") if frames else [])[:limit]
    return {"rows": rows, "truncated": len(rows) == limit,
            "provenance": _prov("NSE-archives", "bulk-block-deals",
                                "VERIFIED" if rows else "UNKNOWN",
                                {"note": "context only; never smart-money labels"})}


def query_positioning(day: str) -> dict:
    """Best-effort positioning legs for a day: each leg reports value or
    abstains (None + flag). No imputation — missing legs stay missing (§1.5)."""
    from app.data import positioning as POS
    try:
        fii = POS.fetch_fii_daily()
    except Exception:  # noqa: BLE001
        fii = None
    try:
        pcr = POS.fetch_nifty_pcr()
    except Exception:  # noqa: BLE001
        pcr = None
    legs = {"fii": fii if fii is not None else "ABSTAIN",
            "pcr": pcr if pcr is not None else "ABSTAIN"}
    return {"day": day, "legs": legs,
            "provenance": _prov("NSE", "positioning",
                                "PARTIAL" if None in (fii, pcr) else "VERIFIED")}


def query_fundamentals(symbol: str, as_of: str) -> dict:
    """PIT fundamentals: availability-gated filings only (§36)."""
    from app.data_acquisition import filings as FIL
    data = FIL.fundamentals_as_of(symbol.upper(), as_of)
    return {**data, "provenance": _prov("NSE-filings", "financial-results",
                                        "VERIFIED" if data["periods"] else "UNKNOWN")}


def _months_between(start: str, end: str, cap: int = 4) -> list[str]:
    import datetime as _dt
    d0 = _dt.date.fromisoformat(start[:10])
    d1 = _dt.date.fromisoformat(end[:10])
    out, cur = [], _dt.date(d0.year, d0.month, 1)
    while cur <= d1 and len(out) < cap:
        out.append(cur.strftime("%Y-%m"))
        cur = _dt.date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
    return out
