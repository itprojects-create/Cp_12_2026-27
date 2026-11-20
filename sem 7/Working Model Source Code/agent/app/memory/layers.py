"""Layered event memory: shallow/interim/deep with half-life decay (prereg §1).

Retrieval score = 0.4*recency + 0.4*relevancy + 0.2*importance.
Recency = 0.5^(age_days / half_life). Relevancy = keyword overlap, no embeddings
(deterministic). Promotion moves one layer deeper with recency reset, logged.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.db import sqlite_conn

LAYERS = ("shallow", "interim", "deep")
HALF_LIFE_DAYS = {"shallow": 5.0, "interim": 20.0, "deep": 90.0}
PROMOTE_TO = {"shallow": "interim", "interim": "deep", "deep": "deep"}


def init_tables() -> None:
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS mem_events
        (id INTEGER PRIMARY KEY AUTOINCREMENT, layer TEXT, content TEXT,
         importance REAL, ref TEXT, available_at TEXT, created_at TEXT,
         access_count INTEGER NOT NULL DEFAULT 0, promotions INTEGER NOT NULL DEFAULT 0)""")
    cols = {r[1] for r in c.execute("PRAGMA table_info(memory_settlements)").fetchall()}
    for col in ("veto REAL", "regime TEXT", "breadth REAL", "size REAL"):
        if col.split()[0] not in cols:
            c.execute(f"ALTER TABLE memory_settlements ADD COLUMN {col}")
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_event(layer: str, content: str, importance: float, ref: str = "",
                available_at: str | None = None) -> int:
    if layer not in LAYERS:
        raise ValueError(f"bad layer {layer!r}")
    if not (0.0 <= importance <= 1.0):
        raise ValueError("importance must be in [0,1]")
    if not content or len(content) > 2000:
        raise ValueError("content must be 1..2000 chars")
    c = sqlite_conn()
    cur = c.execute(
        "INSERT INTO mem_events(layer, content, importance, ref, available_at, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (layer, content, importance, ref, available_at or _now(), _now()))
    c.commit()
    return cur.lastrowid


def _tokens(s: str) -> set[str]:
    return set(w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2)


def _score(importance: float, created_iso: str, half_life: float,
           content: str, query: str, now_iso: str) -> float:
    try:
        now = datetime.fromisoformat(now_iso)
        created = datetime.fromisoformat(created_iso)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - created).total_seconds() / 86400.0)
    except ValueError:
        age_days = 0.0
    recency = 0.5 ** (age_days / half_life)
    qt, ct = _tokens(query), _tokens(content)
    relevancy = (len(qt & ct) / len(qt)) if qt else 0.0
    return 0.4 * recency + 0.4 * min(1.0, relevancy) + 0.2 * importance


def recall(query: str, as_of: str, k_per_layer: int = 3) -> list[dict]:
    """Top-K per layer, PIT-filtered (available_at <= as_of). Access-counted."""
    c = sqlite_conn()
    out: list[dict] = []
    for layer in LAYERS:
        rows = c.execute(
            "SELECT id, content, importance, ref, created_at FROM mem_events"
            " WHERE layer=? AND available_at<=? ORDER BY created_at DESC LIMIT 200",
            (layer, as_of)).fetchall()
        scored = sorted(
            ({"id": r[0], "layer": layer, "content": r[1], "importance": r[2],
              "ref": r[3],
              "score": _score(r[2], r[4], HALF_LIFE_DAYS[layer], r[1], query, as_of)}
             for r in rows),
            key=lambda d: -d["score"])[:k_per_layer]
        for d in scored:
            c.execute("UPDATE mem_events SET access_count=access_count+1 WHERE id=?", (d["id"],))
            out.append(d)
    c.commit()
    return out


def promote(event_id: int) -> str:
    """Move one layer deeper with recency reset. Returns new layer."""
    c = sqlite_conn()
    r = c.execute("SELECT layer FROM mem_events WHERE id=?", (event_id,)).fetchone()
    if not r:
        raise ValueError(f"unknown event {event_id}")
    new_layer = PROMOTE_TO[r[0]]
    c.execute("UPDATE mem_events SET layer=?, created_at=?, promotions=promotions+1 WHERE id=?",
              (new_layer, _now(), event_id))
    c.commit()
    return new_layer
