"""Durable operations log (§16): append-only job/audit trail for later review."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import sqlite_conn


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS operations_log
        (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, job TEXT, event TEXT,
         status TEXT, records INTEGER, errors TEXT, snapshot_id TEXT, note TEXT)""")
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS job_runs
        (job TEXT PRIMARY KEY, last_run_ts TEXT, last_status TEXT)""")
    sqlite_conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(job: str, event: str, status: str = "OK", records: int = 0,
        errors: str = "", snapshot_id: str = "", note: str = "") -> int:
    init_tables()
    cur = sqlite_conn().execute(
        "INSERT INTO operations_log(ts, job, event, status, records, errors,"
        " snapshot_id, note) VALUES (?,?,?,?,?,?,?,?)",
        (_now(), job, event, status, records, errors[:1000], snapshot_id, note[:500]))
    if event in ("finish", "fail"):
        sqlite_conn().execute(
            "INSERT OR REPLACE INTO job_runs(job, last_run_ts, last_status)"
            " VALUES (?,?,?)", (job, _now(), status))
    sqlite_conn().commit()
    return cur.lastrowid


def last_run(job: str) -> dict | None:
    init_tables()
    r = sqlite_conn().execute(
        "SELECT job, last_run_ts, last_status FROM job_runs WHERE job=?", (job,)).fetchone()
    if not r:
        return None
    return {"job": r[0], "last_run_ts": r[1], "last_status": r[2]}


def check_gaps(jobs: list[str], now_iso: str, max_age_hours: float) -> list[dict]:
    """Missed-run detection (§78): jobs with no successful finish within the
    window are EXPECTED RUN MISSING — never silently pretended as collected."""
    from datetime import datetime as _dt
    now = _dt.fromisoformat(now_iso)
    gaps = []
    for job in jobs:
        lr = last_run(job)
        if lr is None:
            gaps.append({"job": job, "gap": "NEVER_RUN"})
            continue
        try:
            age_h = (now - _dt.fromisoformat(lr["last_run_ts"])).total_seconds() / 3600
        except ValueError:
            age_h = float("inf")
        if age_h > max_age_hours or lr["last_status"] not in ("OK",):
            gaps.append({"job": job, "gap": "EXPECTED_RUN_MISSING",
                         "last": lr["last_run_ts"], "status": lr["last_status"],
                         "age_h": round(age_h, 1)})
    return gaps
