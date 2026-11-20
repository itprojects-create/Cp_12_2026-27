"""Corporate-action acquisition store (Phase C, §§19–20).

Normalized §19 schema, idempotent by source_record_id. Filing linkage (§20):
an action is PIT-knowable only via its disclosure — link_to_filing() searches
the immutable event store (same symbol, announcement within 60d before ex-date,
kind-consistent classification); linked actions grade by match strength, the
rest stay PARTIAL/UNKNOWN. sync_verified_to_pit() publishes VERIFIED rows into
the researched PIT table (app/data/corporate_actions.py) with provenance.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.db import sqlite_conn

ACTION_TYPES = ("DIVIDEND", "BONUS", "SPLIT", "RIGHTS", "BUYBACK", "MERGER",
                "DEMERGER", "DELISTING", "SYMBOL_CHANGE", "ISIN_CHANGE",
                "OTHER", "UNKNOWN")

# classification event_type -> action kinds it can disclose
KIND_BY_EVENT = {"DIVIDEND": ("DIVIDEND",), "SPLIT_BONUS": ("SPLIT", "BONUS"),
                 "BOARD_MEETING": (), "EARNINGS": (), "MERGER": ("MERGER", "DEMERGER"),
                 "FUNDRAISING": ("RIGHTS", "BUYBACK"), "REGULATORY": (),
                 "LEADERSHIP": (), "OTHER": ()}


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS corp_actions
        (source_record_id TEXT PRIMARY KEY, exchange TEXT, symbol TEXT, isin TEXT,
         action_type TEXT, announcement_ts TEXT, ex_date TEXT, record_date TEXT,
         effective_date TEXT, payment_date TEXT, ratio TEXT, cash_amount REAL,
         old_symbol TEXT, new_symbol TEXT, source TEXT, source_hash TEXT,
         filing_record_id TEXT, pit_confidence TEXT, ts TEXT)""")
    sqlite_conn().commit()


def normalize(exchange: str, raw: dict) -> dict | None:
    """Raw exchange row -> §19 record. None = unusable (never imputed)."""
    symbol = str(raw.get("symbol", "")).strip().upper()
    if len(symbol) < 3:
        return None
    kind = str(raw.get("action_type", "UNKNOWN")).strip().upper()
    if kind not in ACTION_TYPES:
        kind = "UNKNOWN"
    ex_date = str(raw.get("ex_date", ""))[:10]
    if len(ex_date) != 10:
        return None
    rec = {
        "source_record_id": f"{exchange}-{raw.get('id') or hash_payload(raw)}",
        "exchange": exchange, "symbol": symbol if symbol.endswith(".NS") else symbol + ".NS",
        "isin": str(raw.get("isin", ""))[:12], "action_type": kind,
        "announcement_ts": str(raw.get("announcement_ts", "")) or None,
        "ex_date": ex_date, "record_date": str(raw.get("record_date", ""))[:10] or None,
        "effective_date": str(raw.get("effective_date", ""))[:10] or ex_date,
        "payment_date": str(raw.get("payment_date", ""))[:10] or None,
        "ratio": str(raw.get("ratio", ""))[:32] or None,
        "cash_amount": _num(raw.get("cash_amount")),
        "old_symbol": str(raw.get("old_symbol", ""))[:32] or None,
        "new_symbol": str(raw.get("new_symbol", ""))[:32] or None,
        "source": str(raw.get("source", exchange)),
    }
    rec["source_hash"] = hash_payload(rec)
    return rec


def hash_payload(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()
                          ).hexdigest()[:16]


def _num(v) -> float | None:
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def upsert(rec: dict) -> str:
    """Idempotent write. Returns source_record_id; re-ingest is a no-op."""
    init_tables()
    sqlite_conn().execute(
        "INSERT OR IGNORE INTO corp_actions(source_record_id, exchange, symbol, isin,"
        " action_type, announcement_ts, ex_date, record_date, effective_date,"
        " payment_date, ratio, cash_amount, old_symbol, new_symbol, source, source_hash,"
        " filing_record_id, pit_confidence, ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec["source_record_id"], rec["exchange"], rec["symbol"], rec.get("isin", ""),
         rec["action_type"], rec.get("announcement_ts"), rec["ex_date"],
         rec.get("record_date"), rec.get("effective_date"), rec.get("payment_date"),
         rec.get("ratio"), rec.get("cash_amount"), rec.get("old_symbol"),
         rec.get("new_symbol"), rec["source"], rec["source_hash"], None, "UNKNOWN",
         datetime.now(timezone.utc).isoformat()))
    sqlite_conn().commit()
    return rec["source_record_id"]


def link_to_filing(source_record_id: str) -> dict:
    """§20: bind the action to its disclosure. Strength by kind-consistency;
    unmatched actions stay PARTIAL (announcement_ts present) or UNKNOWN."""
    from app.events import store as ST
    init_tables()
    row = sqlite_conn().execute(
        "SELECT symbol, action_type, ex_date, announcement_ts FROM corp_actions"
        " WHERE source_record_id=?", (source_record_id,)).fetchone()
    if not row:
        return {"linked": False, "reason": "unknown action"}
    symbol, kind, ex_date, ann_ts = row
    cands = sqlite_conn().execute(
        "SELECT record_id, publication_ts FROM raw_events"
        " WHERE symbol=? AND substr(publication_ts,1,10) BETWEEN date(?, '-60 days') AND ?"
        " ORDER BY publication_ts DESC",
        (symbol, ex_date, ex_date)).fetchall()
    best, best_kind_ok = None, False
    for rid, _pub in cands:
        cls = sqlite_conn().execute(
            "SELECT classification FROM event_classifications WHERE record_id=?"
            " ORDER BY version DESC LIMIT 1", (rid,)).fetchone()
        etype = (json.loads(cls[0]).get("event_type") if cls else "OTHER")
        if kind in KIND_BY_EVENT.get(etype, ()):
            best, best_kind_ok = rid, True
            break
        if best is None:
            best = rid
    if best is None:
        conf = "PARTIAL" if ann_ts else "UNKNOWN"
        sqlite_conn().execute(
            "UPDATE corp_actions SET pit_confidence=? WHERE source_record_id=?",
            (conf, source_record_id))
        sqlite_conn().commit()
        return {"linked": False, "pit_confidence": conf,
                "reason": "no disclosure in store window"}
    conf = "VERIFIED" if best_kind_ok else "PARTIAL"
    sqlite_conn().execute(
        "UPDATE corp_actions SET filing_record_id=?, pit_confidence=?"
        " WHERE source_record_id=?", (best, conf, source_record_id))
    sqlite_conn().commit()
    ST._link(source_record_id, best, "discloses")
    return {"linked": True, "filing": best, "pit_confidence": conf,
            "kind_consistent": best_kind_ok}


def sync_verified_to_pit() -> dict:
    """Publish VERIFIED factor-bearing rows (SPLIT/BONUS) into the researched
    PIT table (provenance-tagged). Other kinds have no factor semantics in the
    PIT layer and are reported as skipped — never coerced (§87: no silent
    repair, no fabrication). Idempotent."""
    from app.data import corporate_actions as PIT
    PIT.init_tables()
    rows = sqlite_conn().execute(
        "SELECT symbol, action_type, effective_date FROM corp_actions"
        " WHERE pit_confidence='VERIFIED'").fetchall()
    synced, skipped = 0, []
    for symbol, kind, eff in rows:
        if kind not in ("SPLIT", "BONUS"):
            skipped.append({"symbol": symbol, "kind": kind,
                            "reason": "no factor semantics in PIT layer"})
            continue
        PIT.record(PIT.CorporateAction(symbol=symbol, kind=kind.lower(),
                                       effective_date=eff, factor=1.0,
                                       source="acquisition-verified", verified=True))
        synced += 1
    return {"synced": synced, "skipped_non_factor": skipped}


def actions_for(symbol: str, as_of: str) -> list[dict]:
    """Actions knowable at as_of: linked filing publication <= as_of, or
    announcement_ts <= as_of. Unlinked-undated actions are invisible (PIT)."""
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT source_record_id, action_type, ex_date, filing_record_id,"
        " announcement_ts, pit_confidence FROM corp_actions WHERE symbol=?",
        (symbol.upper(),)).fetchall()
    out = []
    for rid, kind, exd, filing, ann, conf in rows:
        knowable = False
        if filing:
            pub = sqlite_conn().execute(
                "SELECT publication_ts FROM raw_events WHERE record_id=?",
                (filing,)).fetchone()
            if pub and pub[0][:10] <= as_of[:10]:
                knowable = True
        elif ann and ann[:10] <= as_of[:10]:
            knowable = True
        if knowable:
            out.append({"id": rid, "action_type": kind, "ex_date": exd,
                        "pit_confidence": conf})
    return out
