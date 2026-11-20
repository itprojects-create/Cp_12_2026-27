"""Lineage ledger: variants, judging windows, tombstones, lineage (prereg §6).

Statuses: ALIVE | WEAKENED | DEAD. Dead rows are never deleted (seed bank).
Follows repo test convention: callers use TEST- prefixed ids in unit tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import sqlite_conn

STATUSES = ("ALIVE", "WEAKENED", "DEAD")
MAX_LIVING = 8


def init() -> None:
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS evo_variants
        (id TEXT PRIMARY KEY, name TEXT, genome TEXT, status TEXT,
         strikes INTEGER NOT NULL DEFAULT 0, probation INTEGER NOT NULL DEFAULT 0,
         parent_id TEXT, birth_ts TEXT, updated_ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS evo_windows
        (variant_id TEXT, window_no INTEGER, n_decisions INTEGER, ir REAL,
         tokens INTEGER, verdict TEXT, ts TEXT,
         PRIMARY KEY (variant_id, window_no))""")
    c.execute("""CREATE TABLE IF NOT EXISTS evo_tombstones
        (variant_id TEXT PRIMARY KEY, genome TEXT, birth_ts TEXT, death_ts TEXT,
         strikes_log TEXT, death_fingerprint TEXT, cause TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS evo_lineage
        (child_id TEXT PRIMARY KEY, parent_id TEXT, gene_diff TEXT, ts TEXT)""")
    # Append-only transition log the frontend streams (births/deaths/resurrections).
    c.execute("""CREATE TABLE IF NOT EXISTS evo_events
        (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, variant_id TEXT,
         event TEXT, detail TEXT)""")
    c.commit()


def _log_event(variant_id: str, event: str, detail: str = "") -> None:
    sqlite_conn().execute(
        "INSERT INTO evo_events(ts, variant_id, event, detail) VALUES (?,?,?,?)",
        (_now(), variant_id, event, detail))
    sqlite_conn().commit()


def events(since_seq: int = 0) -> list[dict]:
    """Transitions with seq > since_seq, oldest first (WS replay cursor)."""
    init()
    rows = sqlite_conn().execute(
        "SELECT seq, ts, variant_id, event, detail FROM evo_events WHERE seq>? ORDER BY seq",
        (since_seq,)).fetchall()
    return [{"seq": r[0], "ts": r[1], "variant_id": r[2], "event": r[3],
             "detail": r[4] or ""} for r in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def birth(variant_id: str, name: str, genome: dict, parent_id: str | None = None,
          gene_diff: str = "", probation: bool = False) -> None:
    from app.evo.genome import Genome
    Genome(**genome).validate()
    c = sqlite_conn()
    living = c.execute(
        "SELECT COUNT(*) FROM evo_variants WHERE status != 'DEAD'").fetchone()[0]
    if living >= MAX_LIVING:
        raise ValueError(f"population full ({living}/{MAX_LIVING}) — death vacancy required")
    c.execute(
        "INSERT INTO evo_variants(id, name, genome, status, strikes, probation, parent_id, birth_ts, updated_ts)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (variant_id, name, json.dumps(genome, sort_keys=True),
         "WEAKENED" if probation else "ALIVE",
         0, 1 if probation else 0, parent_id, _now(), _now()))
    if parent_id:
        c.execute("INSERT INTO evo_lineage(child_id, parent_id, gene_diff, ts) VALUES (?,?,?,?)",
                  (variant_id, parent_id, gene_diff, _now()))
    c.commit()
    _log_event(variant_id, "resurrection" if probation else "birth", name)


def get(variant_id: str) -> dict | None:
    r = sqlite_conn().execute(
        "SELECT id, name, genome, status, strikes, probation, parent_id FROM evo_variants WHERE id=?",
        (variant_id,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "name": r[1], "genome": json.loads(r[2]), "status": r[3],
            "strikes": r[4], "probation": bool(r[5]), "parent_id": r[6]}


def living() -> list[dict]:
    rows = sqlite_conn().execute(
        "SELECT id, name, genome, status, strikes, probation, parent_id FROM evo_variants"
        " WHERE status != 'DEAD' ORDER BY id").fetchall()
    return [{"id": r[0], "name": r[1], "genome": json.loads(r[2]), "status": r[3],
             "strikes": r[4], "probation": bool(r[5]), "parent_id": r[6]} for r in rows]


def set_status(variant_id: str, status: str, strikes: int, probation: bool = False) -> None:
    if status not in STATUSES:
        raise ValueError(f"bad status {status}")
    sqlite_conn().execute(
        "UPDATE evo_variants SET status=?, strikes=?, probation=?, updated_ts=? WHERE id=?",
        (status, strikes, 1 if probation else 0, _now(), variant_id))
    sqlite_conn().commit()
    _log_event(variant_id, f"status:{status}", f"strikes={strikes}")


def log_window(variant_id: str, window_no: int, n_decisions: int, ir: float,
               tokens: int, verdict: str) -> None:
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO evo_windows(variant_id, window_no, n_decisions, ir, tokens, verdict, ts)"
        " VALUES (?,?,?,?,?,?,?)",
        (variant_id, window_no, n_decisions, ir, tokens, verdict, _now()))
    sqlite_conn().commit()


def bury(variant_id: str, strikes_log: list[str], death_fingerprint: str, cause: str) -> None:
    v = get(variant_id)
    if not v:
        raise ValueError(f"unknown variant {variant_id}")
    c = sqlite_conn()
    c.execute("INSERT OR REPLACE INTO evo_tombstones(variant_id, genome, birth_ts, death_ts,"
              " strikes_log, death_fingerprint, cause) VALUES (?,?,?,?,?,?,?)",
              (variant_id, json.dumps(v["genome"], sort_keys=True), "",
               _now(), json.dumps(strikes_log), death_fingerprint, cause))
    c.execute("UPDATE evo_variants SET status='DEAD', probation=0, updated_ts=? WHERE id=?",
              (_now(), variant_id))
    c.commit()
    _log_event(variant_id, "death", cause)


def seed_bank() -> list[dict]:
    rows = sqlite_conn().execute(
        "SELECT variant_id, genome, death_ts, strikes_log, death_fingerprint, cause FROM evo_tombstones"
        " ORDER BY death_ts").fetchall()
    return [{"variant_id": r[0], "genome": json.loads(r[1]), "death_ts": r[2],
             "strikes_log": json.loads(r[3]), "death_fingerprint": r[4], "cause": r[5]}
            for r in rows]


def window_count(variant_id: str) -> int:
    r = sqlite_conn().execute(
        "SELECT COUNT(*) FROM evo_windows WHERE variant_id=?", (variant_id,)).fetchone()
    return r[0]
