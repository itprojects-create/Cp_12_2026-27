"""Alerting: severity, sinks, dedup (§§13–15).

Sinks: console (always), file outbox (always), webhook/email (only with
explicit env config — otherwise recorded to the outbox as PENDING, never
crashed, never silently dropped). Dedup: same key re-alerts per severity
persistence policy (CRITICAL 4h, WARNING 24h, INFO once); resolutions logged.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from app.db import sqlite_conn

SEVERITY = ("INFO", "WARNING", "CRITICAL")
REPEAT_HOURS = {"CRITICAL": 4.0, "WARNING": 24.0, "INFO": float("inf")}
OUTBOX = os.path.join("data", "alerts.log")


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS alerts
        (alert_key TEXT PRIMARY KEY, severity TEXT, first_seen TEXT,
         last_seen TEXT, occurrence_count INTEGER, resolved_at TEXT, detail TEXT)""")
    sqlite_conn().commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_outbox(record: dict) -> None:
    os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
    with open(OUTBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def fire(alert_key: str, severity: str, detail: str = "") -> dict:
    """Fire (or dedup) an alert. Returns {fired, alert_key, severity, ...}."""
    if severity not in SEVERITY:
        raise ValueError(f"unknown severity {severity!r}")
    init_tables()
    now = _now()
    row = sqlite_conn().execute(
        "SELECT severity, first_seen, last_seen, occurrence_count, resolved_at"
        " FROM alerts WHERE alert_key=?", (alert_key,)).fetchone()
    if row is None or row[4] is not None:
        sqlite_conn().execute(
            "INSERT OR REPLACE INTO alerts(alert_key, severity, first_seen, last_seen,"
            " occurrence_count, resolved_at, detail) VALUES (?,?,?,?,?,?,?)",
            (alert_key, severity, now.isoformat(), now.isoformat(), 1, None,
             detail[:500]))
        sqlite_conn().commit()
        rec = {"fired": True, "alert_key": alert_key, "severity": severity,
               "detail": detail[:500], "ts": now.isoformat(), "repeat": False}
        _emit(rec)
        return rec
    first = datetime.fromisoformat(row[1])
    _last = datetime.fromisoformat(row[2])
    count = row[3] + 1
    sqlite_conn().execute(
        "UPDATE alerts SET last_seen=?, occurrence_count=?, severity=?, detail=?"
        " WHERE alert_key=?",
        (now.isoformat(), count, severity, detail[:500], alert_key))
    sqlite_conn().commit()
    due_hours = (now - _last).total_seconds() / 3600
    if due_hours >= REPEAT_HOURS[severity]:
        rec = {"fired": True, "alert_key": alert_key, "severity": severity,
               "detail": detail[:500], "ts": now.isoformat(), "repeat": True,
               "occurrences": count, "since": first.isoformat()}
        _emit(rec)
        return rec
    return {"fired": False, "alert_key": alert_key, "severity": severity,
            "occurrences": count, "next_repeat_h": round(REPEAT_HOURS[severity] - due_hours, 1)}


def resolve(alert_key: str) -> dict:
    init_tables()
    sqlite_conn().execute("UPDATE alerts SET resolved_at=? WHERE alert_key=?",
                          (_now().isoformat(), alert_key))
    sqlite_conn().commit()
    return {"resolved": alert_key}


def active(severity: str | None = None) -> list[dict]:
    init_tables()
    sql = ("SELECT alert_key, severity, first_seen, last_seen, occurrence_count, detail"
           " FROM alerts WHERE resolved_at IS NULL")
    args: tuple = ()
    if severity:
        sql += " AND severity=?"
        args = (severity,)
    rows = sqlite_conn().execute(sql, args).fetchall()
    return [{"key": r[0], "severity": r[1], "first_seen": r[2], "last_seen": r[3],
             "occurrences": r[4], "detail": r[5]} for r in rows]


def _emit(record: dict) -> None:
    """Console always; file outbox always; webhook/email only when configured
    (else PENDING note in the outbox — durable, never lost)."""
    print(f"ALERT [{record['severity']}] {record['alert_key']}: {record.get('detail','')}")
    sinks = {"console": True, "file": True}
    hook = os.environ.get("QP_ALERT_WEBHOOK", "")
    if hook:
        try:
            import urllib.request
            req = urllib.request.Request(
                hook, data=json.dumps(record).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10):
                sinks["webhook"] = True
        except Exception as e:  # noqa: BLE001 - delivery failure is data, not crash
            sinks["webhook"] = f"FAILED: {type(e).__name__}"
    else:
        sinks["webhook"] = "PENDING (no QP_ALERT_WEBHOOK configured)"
    if os.environ.get("QP_ALERT_EMAIL", ""):
        sinks["email"] = "PENDING (email provider not wired; outbox is the record)"
    else:
        sinks["email"] = "PENDING (no QP_ALERT_EMAIL configured)"
    _write_outbox({**record, "sinks": sinks})


def evict_resolved(older_than_days: int = 90) -> int:
    cutoff = (_now() - timedelta(days=older_than_days)).isoformat()
    cur = sqlite_conn().execute(
        "DELETE FROM alerts WHERE resolved_at IS NOT NULL AND resolved_at < ?",
        (cutoff,))
    sqlite_conn().commit()
    return cur.rowcount
