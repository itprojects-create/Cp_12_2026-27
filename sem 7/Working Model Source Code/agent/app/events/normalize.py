"""Normalize: timestamp validation, symbol form, dedup (§15 data lineage).

Raw dicts {source, symbol, title, timestamp} -> validated records. Rejects:
unknown sources, unparseable/future timestamps, empty titles/symbols.
Dedups on (symbol, source_timestamp, title-hash) — re-ingestion is idempotent.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

SOURCES = ("NSE", "BSE", "FILE")


def _parse_ts(value: object) -> datetime | None:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
            try:
                ts = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            try:
                ts = datetime.fromisoformat(text)
            except ValueError:
                return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def normalize_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if s.endswith("-EQ"):
        s = s[:-3] + ".NS"
    if not s.endswith(".NS"):
        s = s + ".NS"
    return s


def normalize(raw: list[dict], now: datetime | None = None) -> tuple[list[dict], dict]:
    """Returns (records, report). Records: {source, symbol, title,
    source_timestamp (iso), effective_timestamp (iso, = source: exchange feed
    is the discovery channel)}. Future-dated rows are rejected (leakage guard)."""
    now = now or datetime.now(timezone.utc)
    records, seen = [], set()
    rejected = {"bad_source": 0, "bad_symbol": 0, "bad_title": 0,
                "bad_timestamp": 0, "future": 0, "duplicate": 0}
    for r in raw:
        if not isinstance(r, dict) or r.get("source") not in SOURCES:
            rejected["bad_source"] += 1
            continue
        sym = normalize_symbol(r.get("symbol", ""))
        if len(sym) < 5:
            rejected["bad_symbol"] += 1
            continue
        title = str(r.get("title", "")).strip()
        if not title:
            rejected["bad_title"] += 1
            continue
        ts = _parse_ts(r.get("timestamp"))
        if ts is None:
            rejected["bad_timestamp"] += 1
            continue
        if ts > now:
            rejected["future"] += 1
            continue
        key = (sym, ts.isoformat(),
               hashlib.sha256(title.encode()).hexdigest()[:12])
        if key in seen:
            rejected["duplicate"] += 1
            continue
        seen.add(key)
        records.append({"source": r["source"], "symbol": sym, "title": title,
                        "source_timestamp": ts.isoformat(),
                        "effective_timestamp": ts.isoformat()})
    records.sort(key=lambda x: x["source_timestamp"])
    return records, {"n_in": len(raw), "n_kept": len(records), "rejected": rejected}
