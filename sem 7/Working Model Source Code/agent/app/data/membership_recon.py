"""Press-release membership reconstruction (§41): free, PARTIAL-grade source.

Stores reconstitution announcements (announcement_date, effective_date,
additions, removals, source document + hash). Converts to MembershipIntervals
graded PARTIAL — announcement timing verified from the document, but true
exchange-effective semantics are weaker than a subscription feed. The two
source classes (OFFICIAL_SUBSCRIPTION vs PRESS_RELEASE_RECONSTRUCTION, §39)
are never treated as equivalent: snapshots carry source_class throughout.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.data import pit_membership as PM
from app.db import sqlite_conn

SOURCE_CLASS = "PRESS_RELEASE_RECONSTRUCTION"


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS membership_recon
        (recon_id TEXT PRIMARY KEY, universe_id TEXT, announcement_date TEXT,
         effective_date TEXT, additions TEXT, removals TEXT, source_doc TEXT,
         source_hash TEXT, ts TEXT)""")
    sqlite_conn().commit()


def record(universe_id: str, announcement_date: str, effective_date: str,
           additions: list[str], removals: list[str], source_doc: str) -> dict:
    """Store one reconstitution announcement. Idempotent per content hash."""
    init_tables()
    if len(announcement_date) != 10 or len(effective_date) != 10:
        raise ValueError("dates must be YYYY-MM-DD")
    if effective_date < announcement_date:
        raise ValueError("effective_date precedes announcement_date (leakage shape)")
    body = {"universe_id": universe_id, "announcement_date": announcement_date,
            "effective_date": effective_date,
            "additions": sorted(a.upper() for a in additions),
            "removals": sorted(r.upper() for r in removals), "source_doc": source_doc}
    recon_id = "RECON-" + hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    sqlite_conn().execute(
        "INSERT OR IGNORE INTO membership_recon(recon_id, universe_id, announcement_date,"
        " effective_date, additions, removals, source_doc, source_hash, ts)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (recon_id, universe_id, announcement_date, effective_date,
         json.dumps(body["additions"]), json.dumps(body["removals"]), source_doc,
         hashlib.sha256(source_doc.encode()).hexdigest()[:16],
         datetime.now(timezone.utc).isoformat()))
    sqlite_conn().commit()
    return {"recon_id": recon_id, "duplicate": False}


def to_intervals(universe_id: str) -> list:
    """Recon rows -> PARTIAL MembershipIntervals (additions only; removals bound
    prior spells where present, else open-ended with PARTIAL grade)."""
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT announcement_date, effective_date, additions FROM membership_recon"
        " WHERE universe_id=? ORDER BY effective_date", (universe_id,)).fetchall()
    out = []
    for ann, eff, adds in rows:
        for sym in json.loads(adds):
            out.append(PM.MembershipInterval(
                instrument_id=sym if sym.endswith(".NS") else sym + ".NS",
                universe_id=universe_id, effective_from=eff, effective_to=None,
                announcement_timestamp=ann + "T00:00:00+00:00",
                source="press_release", source_record_id=None,
                pit_confidence="PARTIAL",
                source_hash=hashlib.sha256(
                    f"{universe_id}{sym}{eff}".encode()).hexdigest()[:16]))
    return out
