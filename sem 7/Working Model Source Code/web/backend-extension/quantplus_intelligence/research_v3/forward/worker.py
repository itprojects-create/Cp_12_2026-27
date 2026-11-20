"""Durable forward worker (W6.5): calendar-aware jobs, receipts, honest alerts.

Design constraints (blueprint §12 + handoff §7):
- server-owned recurring loop, calendar-aware in Asia/Kolkata; the user's
  browser being open is never a durability claim;
- idempotent JobReceipts (append-only JSONL + ledger JOB_RECEIPT events) with
  per-job lease files for duplicate triggers;
- missed-run detection against the VERIFIED calendar only; unverified years
  never fabricate schedules;
- a catch-up may record that an event was missed but can never backdate a
  live quote or manufacture an eligible fill after the fact;
- clock skew fails closed (a backwards system clock refuses to run);
- alerts are labelled: WEBHOOK_NOT_CONFIGURED (no route), DRY_RUN (route
  configured, not sent), or DELIVERED (real provider response evidence);
- explicit WORKER_NOT_DURABLE when the hosting has not been operator-approved;
- an operator may pause new exposure instantly; resume requires a health ack.
"""
from __future__ import annotations

import json
import os
import socket
import time
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from quantplus_intelligence.exchange_calendar import is_trading_day, session_days
from quantplus_intelligence.research_v3.wave5_common import (
    parse_aware_timestamp,
    semantic_sha256,
)

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_JOBS: tuple[dict, ...] = (
    {"job": "session_lock", "due_ist": "09:15"},
    {"job": "signal_evaluation", "due_ist": "09:20"},
    {"job": "execution_monitor", "due_ist": "10:00"},
    {"job": "action_check", "due_ist": "17:00"},
    {"job": "settlement", "due_ist": "17:30"},
    {"job": "nav_mark", "due_ist": "18:00"},
    {"job": "alert_eval", "due_ist": "18:30"},
)

# Only these jobs can create new exposure. A pause does not disable settlement,
# action checks, marks, alerts, or risk-reducing exit monitoring.
EXPOSURE_INCREASING_JOBS = frozenset({"signal_evaluation"})

ALERT_WEBHOOK_NOT_CONFIGURED = "WEBHOOK_NOT_CONFIGURED"
ALERT_DRY_RUN = "DRY_RUN"
ALERT_DELIVERED = "DELIVERED"
RECEIPT_SCHEMA = "research_v3/forward_job_receipt/1"


class ClockSkewError(RuntimeError):
    pass


class ForwardWorker:
    def __init__(self, ledger, receipts_dir: str | Path, stream_id: str,
                 *, jobs: tuple[dict, ...] | None = None,
                 webhook_url: str | None = None,
                 durable_hosting: bool = False,
                 grace_minutes: int = 120,
                 handlers: dict[str, Callable[[str], dict]] | None = None):
        self.ledger = ledger
        self.receipts_path = Path(receipts_dir) / "wave6_job_receipts.jsonl"
        self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
        self.stream_id = stream_id
        self.jobs = {j["job"]: dict(j, due_ist=j["due_ist"])
                     for j in (jobs or DEFAULT_JOBS)}
        self.webhook_url = webhook_url
        self.durable_hosting = durable_hosting
        self.grace_minutes = grace_minutes
        self.handlers = handlers or {}
        self.paused = False
        self._last_receipt_ts: str | None = None
        self._alerted: set[str] = set()
        self._heartbeat_at: str | None = None

    # ------------------------------------------------------------ receipts
    def receipts(self) -> list[dict]:
        if not self.receipts_path.is_file():
            return []
        return [json.loads(line) for line in
                self.receipts_path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def _write_receipt(self, receipt: dict) -> None:
        encoded = (json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True) + "\n").encode("utf-8")
        with self.receipts_path.open("ab") as h:
            h.write(encoded)
            h.flush()
            os.fsync(h.fileno())

    def _receipt_for(self, job: str, session_date: str) -> dict | None:
        return next((r for r in self.receipts()
                     if r["job"] == job and r["session_date"] == session_date),
                    None)

    def _record(self, job: str, session_date: str, status: str,
                 occurred_at: str, detail: dict) -> dict:
        receipt = {
            "receipt_schema": RECEIPT_SCHEMA,
            "stream_id": self.stream_id,
            "job": job,
            "session_date": session_date,
            "status": status,
            "occurred_at": occurred_at,
            "detail": detail,
        }
        receipt["receipt_id"] = semantic_sha256(
            {"job": job, "session": session_date, "stream": self.stream_id,
             "status": status})
        receipt_lock = self._lease("receipt-log")
        if receipt_lock is None:
            raise RuntimeError("RECEIPT_LOG_LEASE_BUSY")
        try:
            if self._receipt_for(job, session_date) is None:
                self._write_receipt(receipt)
                self.ledger.append("JOB_RECEIPT", occurred_at, receipt,
                                   {"stream": self.stream_id, "job": job,
                                    "session": session_date})
                self._last_receipt_ts = occurred_at
        finally:
            self._unlease(receipt_lock)
        return receipt

    # ------------------------------------------------------------- leasing
    def _lease(self, job: str) -> Any:
        lock = self.receipts_path.parent / f".lease-{job}"
        for _ in range(300):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, json.dumps({
                        "pid": os.getpid(), "host": socket.gethostname(),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }, sort_keys=True).encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return lock
            except (FileExistsError, PermissionError):
                try:
                    payload = json.loads(lock.read_text(encoding="utf-8"))
                    age = time.time() - lock.stat().st_mtime
                    pid = int(payload["pid"])
                    alive = True
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        alive = False
                    if (payload.get("host") == socket.gethostname()
                            and age > 30 and not alive):
                        os.replace(lock, lock.with_name(lock.name + f".{pid}.recovered"))
                        continue
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    pass
                time.sleep(0.01)
        return None

    def _unlease(self, lock: Any) -> None:
        if lock is not None:
            try:
                Path(lock).unlink()
            except FileNotFoundError:
                pass

    # ------------------------------------------------------------ schedule
    def _due_utc(self, job: str, session_date: str) -> datetime:
        """Due instant for a job on one session: IST clock, exact IST offset."""
        hour, minute = (int(x) for x in self.jobs[job]["due_ist"].split(":"))
        ist_due = datetime.fromisoformat(
            f"{session_date}T{hour:02d}:{minute:02d}:00+05:30")
        return ist_due

    def run_due(self, now_utc: str, session_date: str | None = None
                ) -> dict:
        """Run every job whose IST due time has passed for the given session.

        Fail-closed rules: unverified calendar sessions never run; a paused
        worker runs nothing (risk-reducing exits live in the paper book, not
        in live exposure); a backwards clock raises.
        """
        now = parse_aware_timestamp(now_utc, "now_utc")
        if self._last_receipt_ts is not None:
            last = parse_aware_timestamp(self._last_receipt_ts, "last")
            if now < last:
                raise ClockSkewError(
                    "system clock moved backwards; refusing to run (fail-closed)")
        if session_date is None:
            session_date = now.astimezone(IST).date().isoformat()
        verdict = is_trading_day(date_cls.fromisoformat(session_date))
        if verdict is not True:
            return {"ran": [], "skipped": [
                {"job": j, "reason": "SESSION_NOT_A_VERIFIED_TRADING_DAY"}
                for j in self.jobs]}
        ran: list[dict] = []
        skipped: list[dict] = []
        for job in sorted(self.jobs):
            if self.paused and job in EXPOSURE_INCREASING_JOBS:
                skipped.append({"job": job, "reason": "NEW_EXPOSURE_PAUSED"})
                continue
            due = self._due_utc(job, session_date)
            if now < due:
                skipped.append({"job": job, "reason": "NOT_DUE_YET"})
                continue
            if self._receipt_for(job, session_date) is not None:
                skipped.append({"job": job, "reason": "ALREADY_DONE"})
                continue
            lock = self._lease(job)
            if lock is None:
                skipped.append({"job": job, "reason": "LEASE_BUSY"})
                continue
            try:
                handler = self.handlers.get(job)
                detail = (handler(session_date) if handler
                          else {"default": "no handler registered; receipt only"})
                if self.paused and job == "execution_monitor":
                    detail = {**detail, "new_exposure_paused": True,
                              "risk_reducing_exits_allowed": True}
                receipt = self._record(job, session_date, "OK", now_utc, detail)
                ran.append(receipt)
            except Exception as exc:                      # noqa: BLE001
                receipt = self._record(job, session_date, "FAILED", now_utc,
                                       {"error": f"{type(exc).__name__}: {exc}"})
                ran.append(receipt)
            finally:
                self._unlease(lock)
        self._heartbeat_at = now_utc
        return {"ran": ran, "skipped": skipped, "session_date": session_date}

    # ------------------------------------------------------- missed runs --
    def detect_missed_runs(self, now_utc: str, session_date: str) -> list[dict]:
        """Report jobs due for a verified session with no receipt, after grace.

        The output is an ALERT proposal list.  It never backfills data: a
        missed event is recorded as missed, and the catch-up path may only
        record the miss, never a retroactive observed price.
        """
        verdict = is_trading_day(date_cls.fromisoformat(session_date))
        if verdict is not True:
            return []
        now = parse_aware_timestamp(now_utc, "now_utc")
        misses: list[dict] = []
        for job in sorted(self.jobs):
            due = self._due_utc(job, session_date)
            grace = due + timedelta(minutes=self.grace_minutes)
            if now <= grace:
                continue
            if self._receipt_for(job, session_date) is None:
                alert_key = f"{job}:{session_date}"
                miss = {"job": job, "session_date": session_date,
                        "alert_key": alert_key,
                        "due_utc": due.isoformat(),
                        "status": "MISSED_RUN"}
                if alert_key not in self._alerted:
                    self._alerted.add(alert_key)
                    self._alert(f"forward worker: {job} MISSED for "
                                f"{session_date}",
                                f"job={job} session={session_date} "
                                f"due={due.isoformat()}", now_utc)
                    miss["alert"] = self.alert_status()
                misses.append(miss)
        return misses

    def catch_up(self, now_utc: str, session_date: str) -> dict:
        """Idempotent catch-up: records the miss; NEVER backfills quotes."""
        misses = self.detect_missed_runs(now_utc, session_date)
        recorded = []
        for miss in misses:
            existing = self._receipt_for(miss["job"], session_date)
            if existing is None:
                receipt = self._record(
                    miss["job"], session_date, "MISSED_CATCH_UP", now_utc,
                    {"note": "missed run recorded; no retroactive observed "
                             "price was used", "alert_key": miss["alert_key"]})
                recorded.append(receipt)
        return {"recorded": recorded, "misses": misses}

    # -------------------------------------------------------------- alerts
    def alert_status(self) -> dict:
        if not self.webhook_url:
            return {"status": ALERT_WEBHOOK_NOT_CONFIGURED,
                    "delivered": False,
                    "note": "QP_ALERT_WEBHOOK_URL absent; alert NOT delivered"}
        return {"status": ALERT_DRY_RUN,
                "delivered": False,
                "note": "route configured; this module never sends network "
                        "traffic in tests — DELIVERED requires real delivery "
                        "evidence recorded by the operator's host"}

    def _alert(self, subject: str, body: str, now_utc: str) -> None:
        self.ledger.append("RISK_EVENT", now_utc,
                           {"event_kind": "WORKER_ALERT",
                            "subject": subject, "body": body,
                            "stream_id": self.stream_id,
                            "alert_status": self.alert_status()},
                           {"stream": self.stream_id, "alert": subject})

    def heartbeat(self, now_utc: str, detail: dict | None = None) -> dict:
        """Persist a watchdog heartbeat without claiming durable hosting."""
        parse_aware_timestamp(now_utc, "now_utc")
        self._heartbeat_at = now_utc
        payload = {"event_kind": "WORKER_HEARTBEAT", "stream_id": self.stream_id,
                   "detail": dict(detail or {}),
                   "worker_label": ("DURABLE" if self.durable_hosting
                                    else "WORKER_NOT_DURABLE")}
        self.ledger.append("RISK_EVENT", now_utc, payload,
                           {"stream": self.stream_id, "heartbeat": now_utc})
        return payload

    def watchdog(self, now_utc: str, *, max_age_seconds: int = 120) -> dict:
        now = parse_aware_timestamp(now_utc, "now_utc")
        if self._heartbeat_at is None:
            return {"status": "HEARTBEAT_MISSING", "healthy": False,
                    "worker_label": self.delivery_readiness()["worker_label"]}
        heartbeat = parse_aware_timestamp(self._heartbeat_at, "heartbeat_at")
        age = (now - heartbeat).total_seconds()
        status = "HEALTHY" if 0 <= age <= max_age_seconds else "HEARTBEAT_EXPIRED"
        return {"status": status, "healthy": status == "HEALTHY",
                "heartbeat_at": self._heartbeat_at, "age_seconds": age,
                "max_age_seconds": max_age_seconds,
                "worker_label": self.delivery_readiness()["worker_label"]}

    # ---------------------------------------------------------- readiness
    def delivery_readiness(self) -> dict:
        return {
            "worker_durable": self.durable_hosting,
            "worker_label": ("DURABLE" if self.durable_hosting
                             else "WORKER_NOT_DURABLE"),
            "webhook": self.alert_status(),
            "note": "Windows Task Scheduler on a sleeping PC is not "
                    "'always-on'; durable hosting requires operator approval",
        }

    # ------------------------------------------------------ pause / resume
    def pause(self, now_utc: str, reason: str) -> dict:
        self.paused = True
        self.ledger.append("RISK_EVENT", now_utc,
                           {"event_kind": "WORKER_PAUSED", "reason": reason,
                            "stream_id": self.stream_id},
                           {"stream": self.stream_id, "pause": reason,
                            "at": now_utc})
        return {"paused": True}

    def resume(self, now_utc: str, *, health_ack: bool) -> dict:
        if not health_ack:
            return {"paused": True,
                    "reason": "RESUME_REQUIRES_HEALTH_ACK"}
        self.paused = False
        self.ledger.append("RISK_EVENT", now_utc,
                           {"event_kind": "WORKER_RESUMED",
                            "stream_id": self.stream_id},
                           {"stream": self.stream_id, "resume": now_utc})
        return {"paused": False}

    def status(self) -> dict:
        receipts = self.receipts()
        return {
            "stream_id": self.stream_id,
            "paused": self.paused,
            "n_receipts": len(receipts),
            "last_receipt_at": (receipts[-1]["occurred_at"] if receipts
                                 else None),
            "heartbeat": ({"status": "RECORDED_NOT_AGE_EVALUATED",
                           "heartbeat_at": self._heartbeat_at}
                          if self._heartbeat_at else
                          {"status": "HEARTBEAT_MISSING", "healthy": False}),
            "readiness": self.delivery_readiness(),
        }
