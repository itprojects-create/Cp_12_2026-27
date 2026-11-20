"""Filing store: financial results + shareholding with revision PIT (§§34–38).

Raw XBRL/PDF artifacts via store_raw (never coupled to one schema — parser is
separate). Normalized filing rows carry market-availability timestamps
(broadcast + buffer); period-end is NEVER the eligibility clock (§36).
Revisions append (§38): the row visible at as_of is the latest revision with
availability <= as_of. Sanity checks (§88) detect only — company figures are
never altered to fit identities.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.data_acquisition import base as B
from app.data_acquisition import util as U
from app.data_acquisition import xbrl as XBRL
from app.db import sqlite_conn

AVAILABILITY_BUFFER_S = 900


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS filings
        (filing_id TEXT PRIMARY KEY, symbol TEXT, filing_type TEXT,
         period_start TEXT, period_end TEXT, standalone_consolidated TEXT,
         broadcast_ts TEXT, submission_ts TEXT, availability_ts TEXT,
         revision_of TEXT, revision_n INTEGER, xbrl_hash TEXT, pdf_hash TEXT,
         namespace TEXT, facts TEXT, sanity_flags TEXT, ts TEXT)""")
    sqlite_conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def availability_of(broadcast_ts: str, buffer_s: int = AVAILABILITY_BUFFER_S) -> str:
    b = datetime.fromisoformat(broadcast_ts)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return (b + timedelta(seconds=buffer_s)).isoformat()


def ingest_filing(symbol: str, filing_type: str, period_start: str, period_end: str,
                  broadcast_ts: str, xbrl_bytes: bytes | None = None,
                  pdf_bytes: bytes | None = None, day: str | None = None,
                  standalone_consolidated: str | None = None,
                  submission_ts: str | None = None,
                  collector_version: str = "filings-v1") -> dict:
    """Store a filing + revision chain. Same (symbol, type, period, broadcast)
    re-ingested -> same filing_id (idempotent). A later broadcast for the same
    (symbol, type, period) becomes a NEW revision (old versions preserved)."""
    init_tables()
    day = day or datetime.now(timezone.utc).date().isoformat()
    xbrl_hash = pdf_hash = ""
    facts, namespace, sanity = {}, "", []
    if xbrl_bytes:
        xart = B.store_raw("NSE", f"filings-{filing_type}", day,
                           f"{symbol}_{period_end}.xml", xbrl_bytes,
                           collector_version=collector_version)
        xbrl_hash = xart["sha256"]
        parsed = XBRL.parse_xbrl(xbrl_bytes)
        namespace = parsed["namespace"]
        for k, v in parsed["facts"].items():
            facts[k] = v["value"]
        sanity = XBRL.parse_sanity(parsed, period_start, period_end)
    if pdf_bytes:
        part = B.store_raw("NSE", f"filings-{filing_type}", day,
                           f"{symbol}_{period_end}.pdf", pdf_bytes,
                           collector_version=collector_version)
        pdf_hash = part["sha256"]
    base_id = f"FIL-{symbol}-{filing_type}-{period_end}"
    prior = sqlite_conn().execute(
        "SELECT filing_id, revision_n FROM filings WHERE symbol=? AND filing_type=?"
        " AND period_end=? ORDER BY revision_n DESC LIMIT 1",
        (symbol, filing_type, period_end)).fetchone()
    if prior and _same_content(prior[0], xbrl_hash, pdf_hash, broadcast_ts):
        return {"filing_id": prior[0], "duplicate": True, "revision_n": prior[1]}
    revision_of, revision_n = (prior[0], prior[1] + 1) if prior else (None, 1)
    filing_id = base_id if revision_n == 1 else f"{base_id}-r{revision_n}"
    sqlite_conn().execute(
        "INSERT INTO filings(filing_id, symbol, filing_type, period_start, period_end,"
        " standalone_consolidated, broadcast_ts, submission_ts, availability_ts,"
        " revision_of, revision_n, xbrl_hash, pdf_hash, namespace, facts, sanity_flags, ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (filing_id, symbol, filing_type, period_start, period_end,
         standalone_consolidated, broadcast_ts, submission_ts,
         availability_of(broadcast_ts), revision_of, revision_n, xbrl_hash, pdf_hash,
         namespace, json.dumps(facts, sort_keys=True), json.dumps(sanity), _now()))
    sqlite_conn().commit()
    return {"filing_id": filing_id, "duplicate": False, "revision_n": revision_n,
            "sanity": sanity}


def _same_content(filing_id: str, xbrl_hash: str, pdf_hash: str, broadcast_ts: str) -> bool:
    r = sqlite_conn().execute(
        "SELECT xbrl_hash, pdf_hash, broadcast_ts FROM filings WHERE filing_id=?",
        (filing_id,)).fetchone()
    return bool(r) and (r[0], r[1], r[2]) == (xbrl_hash, pdf_hash, broadcast_ts)


def visible_filing(symbol: str, filing_type: str, period_end: str, as_of: str) -> dict | None:
    """Latest revision with availability <= as_of. Period-end never gates (§36)."""
    init_tables()
    r = sqlite_conn().execute(
        "SELECT filing_id, revision_n, availability_ts, facts, broadcast_ts FROM filings"
        " WHERE symbol=? AND filing_type=? AND period_end=? AND availability_ts <= ?"
        " ORDER BY revision_n DESC LIMIT 1",
        (symbol, filing_type, period_end, as_of)).fetchone()
    if not r:
        return None
    return {"filing_id": r[0], "revision": r[1], "availability_ts": r[2],
            "facts": json.loads(r[3]), "broadcast_ts": r[4]}


def fundamentals_as_of(symbol: str, as_of: str,
                       filing_type: str = "financial-results") -> dict:
    """PIT fundamentals: all periods with availability <= as_of (latest per
    period). Never exposes a period-end-eligible-but-unpublished filing."""
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT period_end, availability_ts, facts, revision_n FROM filings"
        " WHERE symbol=? AND filing_type=? AND availability_ts <= ?"
        " ORDER BY period_end DESC",
        (symbol, filing_type, as_of)).fetchall()
    seen, out = set(), []
    for period_end, avail, facts, rev in rows:
        if period_end in seen:
            continue
        seen.add(period_end)
        out.append({"period_end": period_end, "availability_ts": avail,
                    "facts": json.loads(facts), "revision": rev})
    return {"symbol": symbol, "as_of": as_of, "periods": out,
            "pit_note": "eligibility by availability_ts only; period-end never gates (§36)"}
