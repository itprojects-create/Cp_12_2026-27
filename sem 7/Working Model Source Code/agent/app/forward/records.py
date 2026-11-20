"""Forward decision records (§47): pinned context, UNSETTLED outcomes.

Every forward paper decision pins decision ts, strategy version/fingerprint,
desired vs actual paper position, market/event/membership state, snapshot id,
and price/cost/slippage assumptions. Outcome starts UNSETTLED (§48) — only
settle.py may write it, exactly once, after maturity.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.db import sqlite_conn


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS forward_decisions
        (decision_id TEXT PRIMARY KEY, ts TEXT, instrument TEXT, strategy_id TEXT,
         strategy_fp TEXT, desired REAL, paper REAL, market_state TEXT,
         event_state TEXT, membership_state TEXT, snapshot_id TEXT,
         price REAL, cost REAL, slippage REAL, outcome TEXT, settled_ts TEXT)""")
    sqlite_conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_decision(ts: str, instrument: str, strategy_id: str, strategy_fp: str,
                    desired: float, paper: float, market_state: dict | None = None,
                    event_state: dict | None = None,
                    membership_state: dict | None = None,
                    snapshot_id: str = "", price: float = 0.0,
                    cost: float = 0.0, slippage: float = 0.0) -> dict:
    """Write one UNSETTLED forward record. Idempotent per content hash."""
    init_tables()
    body = {"ts": ts, "instrument": instrument, "strategy_id": strategy_id,
            "strategy_fp": strategy_fp, "desired": desired, "paper": paper}
    decision_id = "FWD-" + hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    sqlite_conn().execute(
        "INSERT OR IGNORE INTO forward_decisions(decision_id, ts, instrument, strategy_id,"
        " strategy_fp, desired, paper, market_state, event_state, membership_state,"
        " snapshot_id, price, cost, slippage, outcome, settled_ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (decision_id, ts, instrument, strategy_id, strategy_fp, desired, paper,
         json.dumps(market_state or {}, sort_keys=True),
         json.dumps(event_state or {}, sort_keys=True),
         json.dumps(membership_state or {}, sort_keys=True),
         snapshot_id, price, cost, slippage, "UNSETTLED", ""))
    sqlite_conn().commit()
    return {"decision_id": decision_id, "outcome": "UNSETTLED"}


def unsettled() -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT decision_id, ts, instrument, strategy_id FROM forward_decisions"
        " WHERE outcome='UNSETTLED' ORDER BY ts").fetchall()
    return [{"decision_id": r[0], "ts": r[1], "instrument": r[2],
             "strategy_id": r[3]} for r in rows]


def matured_evidence() -> list[dict]:
    """Only settled rows are retrievable as evidence (§50: agents never see
    unsettled future labels)."""
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT decision_id, ts, instrument, outcome FROM forward_decisions"
        " WHERE outcome <> 'UNSETTLED' ORDER BY ts").fetchall()
    return [{"decision_id": r[0], "ts": r[1], "instrument": r[2],
             "outcome": r[3]} for r in rows]
