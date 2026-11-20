"""Operator kill switch (Day 6): halt new sessions without losing audit state.

One row in `control_state`. The API consults it on every new-session request; a
halted system stays halted until a human explicitly releases it (the switch never
auto-clears). Pure stdlib + SQLite — no LLM, no network.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import sqlite_conn

_KEY = "kill_switch"


def _init() -> None:
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS control_state
        (key TEXT PRIMARY KEY, value TEXT, reason TEXT, updated_ts TEXT)""")
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status() -> dict:
    _init()
    r = sqlite_conn().execute(
        "SELECT value, reason, updated_ts FROM control_state WHERE key=?", (_KEY,)).fetchone()
    if not r:
        return {"engaged": False, "reason": "", "updated_ts": None}
    return {"engaged": r[0] == "engaged", "reason": r[1] or "", "updated_ts": r[2]}


def is_engaged() -> bool:
    return status()["engaged"]


def engage(reason: str = "") -> dict:
    _init()
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO control_state(key, value, reason, updated_ts) VALUES (?,?,?,?)",
        (_KEY, "engaged", reason, _now()))
    sqlite_conn().commit()
    return status()


def release() -> dict:
    _init()
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO control_state(key, value, reason, updated_ts) VALUES (?,?,?,?)",
        (_KEY, "released", "", _now()))
    sqlite_conn().commit()
    return status()
