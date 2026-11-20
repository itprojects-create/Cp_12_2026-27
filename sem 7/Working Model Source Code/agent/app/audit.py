"""Read-only audit export (Day 6): one JSON blob the frontend / RA review can pull.

Purely SELECTs across the SQLite ledger — sessions, theses, evo transitions,
tombstones, token usage, and control state. No writes, no LLM, no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app import control
from app.db import sqlite_conn


def _rows(sql: str, args: tuple = ()) -> list[dict]:
    cur = sqlite_conn().execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def export(limit: int = 1000) -> dict:
    """Return the audit trail. `limit` bounds sessions/events (newest first)."""
    from app.evo import store
    store.init()  # ensure evo tables exist even on a fresh ledger
    sessions = _rows(
        "SELECT id, instrument, as_of, config_hash, status, decision FROM sessions"
        " ORDER BY rowid DESC LIMIT ?", (limit,))
    for s in sessions:
        if s.get("decision"):
            try:
                s["decision"] = json.loads(s["decision"])
            except (TypeError, ValueError):
                pass
    theses = _rows(
        "SELECT instrument, version, status, body, created_at FROM theses"
        " ORDER BY created_at DESC LIMIT ?", (limit,))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "counts": {
            "sessions": sqlite_conn().execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "theses": sqlite_conn().execute("SELECT COUNT(*) FROM theses").fetchone()[0],
            "evo_windows": sqlite_conn().execute("SELECT COUNT(*) FROM evo_windows").fetchone()[0],
            "evo_tombstones": sqlite_conn().execute("SELECT COUNT(*) FROM evo_tombstones").fetchone()[0],
        },
        "sessions": sessions,
        "theses": theses,
        "evo_events": store.events(0)[-limit:] if limit else [],
        "seed_bank": store.seed_bank(),
        "usage_daily": _rows("SELECT day, tokens FROM usage_daily ORDER BY day DESC LIMIT ?", (limit,)),
        "control": control.status(),
    }
