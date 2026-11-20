"""Centralized data registry: versions, hashes, PIT/burn states, usage (§§63-65).

Burn states (dataset assets): UNSEEN → EXPLORATORY → DEVELOPMENT → VALIDATION
→ BURNED, plus FORWARD (promotion-grade) and ARCHIVAL. Transitions are ONE-WAY
toward burned (UNSEEN never returns once touched). The experiment access policy
refuses promotion claims resting on BURNED-only evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import sqlite_conn

REGISTRY_VERSION = "registry-v1"

STATES = ("UNSEEN", "EXPLORATORY", "DEVELOPMENT", "VALIDATION",
          "BURNED", "FORWARD", "ARCHIVAL")

# Allowed transitions (one-way toward burned; FORWARD/ARCHIVAL terminal-ish).
NEXT = {
    "UNSEEN": ("EXPLORATORY", "DEVELOPMENT", "VALIDATION", "BURNED", "FORWARD", "ARCHIVAL"),
    "EXPLORATORY": ("DEVELOPMENT", "VALIDATION", "BURNED", "ARCHIVAL"),
    "DEVELOPMENT": ("VALIDATION", "BURNED", "ARCHIVAL"),
    "VALIDATION": ("BURNED", "ARCHIVAL"),
    "BURNED": ("ARCHIVAL",),
    "FORWARD": ("ARCHIVAL",),
    "ARCHIVAL": (),
}

SEED = (
    ("backtest-2021-2026", "BURNED", "12 DSR trials; falsification-only"),
    ("blind-2015-2020", "BURNED", "single survival read"),
    ("v1-2023-2024", "BURNED", "direction-finding reuse"),
    ("v5-2025-disjoint", "BURNED", "direction-finding reuse"),
    ("v3rd-2026-clean", "BURNED", "m3 + retry reads"),
    ("v4-2022-blind", "BURNED", "H1 read"),
    ("v6-2026h2-unburned", "VALIDATION", "partial 14/24"),
    ("v7-2026h2-unburned", "VALIDATION", "partial 10/24"),
    ("forward-from-2026-10-10", "FORWARD", "only promotion-grade source"),
    ("event-feed-forward", "FORWARD", "announcements since experiment freeze"),
    ("membership-history-v1", "DEVELOPMENT", "PIT layer built on it; promotion use requires VERIFIED snapshots"),
)


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS dataset_registry
        (name TEXT PRIMARY KEY, state TEXT, version TEXT, first_available TEXT,
         last_updated TEXT, raw_hash TEXT, processed_hash TEXT, source TEXT,
         pit_status TEXT, usage_count INTEGER NOT NULL DEFAULT 0, note TEXT)""")
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS dataset_usage
        (ts TEXT, dataset TEXT, experiment TEXT, purpose TEXT)""")
    sqlite_conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register(name: str, state: str = "UNSEEN", version: str = REGISTRY_VERSION,
             source: str = "", pit_status: str = "UNKNOWN", note: str = "") -> dict:
    init_tables()
    if state not in STATES:
        raise ValueError(f"unknown burn state {state!r}")
    sqlite_conn().execute(
        "INSERT OR IGNORE INTO dataset_registry(name, state, version, first_available,"
        " last_updated, source, pit_status, note) VALUES (?,?,?,?,?,?,?,?)",
        (name, state, version, _now(), _now(), source, pit_status, note[:300]))
    sqlite_conn().commit()
    return status_of(name)


def seed_known() -> dict:
    n = 0
    for name, state, note in SEED:
        before = status_of(name)
        register(name, state, note=note)
        if before is None:
            n += 1
    return {"seeded": n, "total": len(list_datasets())}


def status_of(name: str) -> dict | None:
    init_tables()
    r = sqlite_conn().execute(
        "SELECT name, state, version, source, pit_status, usage_count, note"
        " FROM dataset_registry WHERE name=?", (name,)).fetchone()
    if not r:
        return None
    return {"name": r[0], "state": r[1], "version": r[2], "source": r[3],
            "pit_status": r[4], "usage_count": r[5], "note": r[6]}


def transition(name: str, to: str) -> dict:
    """One-way burn transition. Backward moves raise (UNSEEN never returns)."""
    init_tables()
    cur = status_of(name)
    if cur is None:
        raise ValueError(f"unknown dataset {name!r} — register first")
    if to not in STATES:
        raise ValueError(f"unknown burn state {to!r}")
    if to not in NEXT[cur["state"]] and to != cur["state"]:
        raise ValueError(f"burn transition {cur['state']} -> {to} forbidden (one-way)")
    sqlite_conn().execute(
        "UPDATE dataset_registry SET state=?, last_updated=? WHERE name=?",
        (to, _now(), name))
    sqlite_conn().commit()
    return status_of(name)


def list_datasets() -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT name, state, version, source, pit_status, usage_count, note"
        " FROM dataset_registry ORDER BY name").fetchall()
    return [{"name": r[0], "state": r[1], "version": r[2], "source": r[3],
             "pit_status": r[4], "usage_count": r[5], "note": r[6]} for r in rows]


def record_usage(dataset: str, experiment: str, purpose: str) -> None:
    init_tables()
    if status_of(dataset) is None:
        register(dataset, "UNSEEN", note="auto-registered on first use")
    sqlite_conn().execute(
        "INSERT INTO dataset_usage(ts, dataset, experiment, purpose) VALUES (?,?,?,?)",
        (_now(), dataset, experiment, purpose[:200]))
    sqlite_conn().execute(
        "UPDATE dataset_registry SET usage_count = usage_count + 1,"
        " last_updated=? WHERE name=?", (_now(), dataset))
    sqlite_conn().commit()


def check_access(dataset: str, purpose: str) -> dict:
    """Experiment data-access policy (§65): promotion on BURNED-only evidence
    is NOT SUFFICIENT — the runner must refuse the claim (not crash the run)."""
    st = status_of(dataset)
    if st is None:
        return {"allowed": True, "dataset": dataset, "state": "UNSEEN",
                "note": "unknown dataset treated as UNSEEN (exploratory only)"}
    if purpose == "promotion" and st["state"] in ("BURNED", "DEVELOPMENT", "EXPLORATORY"):
        return {"allowed": False, "dataset": dataset, "state": st["state"],
                "note": "candidate promotion + BURNED-only dataset = NOT SUFFICIENT"}
    return {"allowed": True, "dataset": dataset, "state": st["state"], "note": "ok"}
