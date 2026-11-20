"""W0.5 worker reliability: heartbeat, missed-session detection and alert interface.

The Windows Task Scheduler registration (agent-service/scripts/register-forecast-jobs.ps1)
runs settle/daily/tournament/catchup on IST weekdays with StartWhenAvailable+WakeToRun,
but uses InteractiveToken: a sleeping machine or a logged-off session silently skips a
run. This module makes that visible instead of silent:

- record(job, ok, detail): append-only heartbeat JSONL (idempotent writes, UTC stamps).
- status(): per-job OK / MISSED / NOT_DUE_YET for today's verified NSE session plus a
  MISSED_SESSION alarm when no daily heartbeat covers the last completed session.
- alert(subject, body): posts to QP_ALERT_WEBHOOK_URL when configured; otherwise every
  result is labelled NOT_CONFIGURED — a missing route is never assumed operational.

No job is re-run here and no forecast is backfilled; catchup remains the only
recovery path and stays idempotent (cards dedupe, settlements only fill matured rows).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from ..exchange_calendar import is_trading_day

REPORTS = Path(os.environ.get("FORECAST_REPORT_DIR", "data/forecast_reports"))
HEARTBEAT_PATH = REPORTS / "worker_heartbeat.jsonl"
STATUS_PATH = REPORTS / "worker_heartbeat_status.json"

IST = timezone(timedelta(hours=5, minutes=30))
# Due times after the 15:30 NSE close (matching the registered Task Scheduler jobs).
DUE_TIMES = {"settle": time(16, 15), "daily": time(16, 30), "tournament": time(17, 30),
             "catchup": time(21, 0)}
GRACE = timedelta(minutes=30)      # a run up to 30 min late is still OK
UPTIME_LABEL = "CONDITIONAL"       # Windows laptop + InteractiveToken: no 24/7 claim


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record(job: str, ok: bool, detail: str = "", path: Path | None = None) -> dict:
    """Append one heartbeat line. Never raises into the caller's job result."""
    path = path or HEARTBEAT_PATH
    entry = {"job": job, "ok": bool(ok), "detail": detail[:400],
             "at_utc": _now().isoformat(), "session_date": _ist_date().isoformat()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except OSError:  # heartbeat failure must not fail the job that produced it
        return {"recorded": False, "entry": entry}
    return {"recorded": True, "entry": entry}


def _ist_date(now: datetime | None = None) -> date:
    return (now or _now()).astimezone(IST).date()


def _last_completed_session(today: date | None = None) -> date | None:
    """Most recent verified NSE regular session whose close has passed (IST)."""
    now = _now().astimezone(IST)
    day = (today or now.date())
    close_today = now.time() >= time(15, 30)
    for _ in range(15):
        verdict = is_trading_day(day)
        if verdict and (day < now.date() or (day == now.date() and close_today)):
            return day
        day -= timedelta(days=1)
    return None


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def status(now: datetime | None = None, path: Path | None = None) -> dict:
    """Per-job health for the current session, plus MISSED_SESSION detection."""
    path = path or HEARTBEAT_PATH
    now = now or _now()
    ist_now = now.astimezone(IST)
    session = _ist_date(now)
    session_is_trading = bool(is_trading_day(session))
    entries = _lines(path)
    per_job: dict[str, dict] = {}
    for job, due_time in DUE_TIMES.items():
        due_today = session_is_trading and ist_now.time() >= due_time
        todays = [e for e in entries if e.get("job") == job and e.get("session_date") == session.isoformat()]
        if not due_today:
            per_job[job] = {"state": "NOT_DUE_YET", "runs_today": len(todays), "due_at_ist": due_time.isoformat()}
        elif todays and any(e.get("ok") for e in todays):
            last = max(e["at_utc"] for e in todays if e.get("ok"))
            per_job[job] = {"state": "OK", "runs_today": len(todays), "last_ok_utc": last,
                            "due_at_ist": due_time.isoformat()}
        elif todays:
            per_job[job] = {"state": "FAILED_TODAY", "runs_today": len(todays),
                            "due_at_ist": due_time.isoformat()}
        else:
            # nothing recorded today and the due time has passed with the grace window
            overdue = datetime.combine(session, due_time, IST) + GRACE
            per_job[job] = {"state": "MISSED" if ist_now >= overdue else "DUE_RUNNING_LATE",
                            "runs_today": 0, "due_at_ist": due_time.isoformat()}
    # Missed-session detection: the last completed session must have a daily heartbeat.
    # If heartbeat monitoring did not exist yet for that session, the honest state is
    # UNMONITORED (unknown), not MISSED — never fabricate a failure or an all-clear.
    last_session = _last_completed_session()
    missed_session = None
    if last_session:
        covered = [e for e in entries if e.get("job") == "daily"
                   and e.get("session_date") == last_session.isoformat() and e.get("ok")]
        monitored = any(e.get("session_date", "") <= last_session.isoformat() for e in entries)
        if covered:
            state, note = "OK", ""
        elif not monitored:
            state = "UNMONITORED"
            note = (f"heartbeat monitoring started after {last_session.isoformat()}; "
                    "no coverage exists for that session — verify manually via "
                    "schedule_daily.log, or run `catchup` if the day must not be lost")
        else:
            state = "MISSED_SESSION"
            note = (f"no successful daily job recorded for {last_session.isoformat()}; "
                    "run `catchup` (idempotent; never backfills a forecast)")
        missed_session = {
            "last_completed_session": last_session.isoformat(),
            "daily_heartbeat_covers_it": bool(covered),
            "state": state,
            "note": note,
        }
    result = {
        "generated_at": now.isoformat(),
        "uptime": UPTIME_LABEL,
        "uptime_note": "Windows Task Scheduler + InteractiveToken: runs stop on sleep/logoff. "
                       "CONDITIONAL until an always-on host runs the worker (see ops runbook).",
        "session_today": session.isoformat(),
        "session_is_trading_day": session_is_trading,
        "jobs": per_job,
        "missed_session": missed_session,
        "alert_route": alert_route(),
        "heartbeat_path": str(path),
    }
    unhealthy = any(j["state"] in ("MISSED", "FAILED_TODAY") for j in per_job.values()) or (
        missed_session and missed_session["state"] == "MISSED_SESSION")
    result["overall"] = "DEGRADED" if unhealthy else "OK"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass
    return result


def alert_route() -> dict:
    url = os.environ.get("QP_ALERT_WEBHOOK_URL", "").strip()
    return {"configured": bool(url), "state": "CONFIGURED" if url else "NOT_CONFIGURED",
            "url": None}   # never echo the destination


def alert(subject: str, body: str) -> dict:
    """External notification through the configured webhook; NOT_CONFIGURED when absent."""
    route = alert_route()
    if not route["configured"]:
        return {"sent": False, "state": "NOT_CONFIGURED",
                "note": "set QP_ALERT_WEBHOOK_URL to enable external alerts"}
    payload = json.dumps({"subject": subject[:200], "body": body[:2000],
                          "source": "quantplus-forecast-worker",
                          "at_utc": _now().isoformat()}).encode()
    request = urllib.request.Request(  # noqa: S310 - operator-configured destination
        os.environ["QP_ALERT_WEBHOOK_URL"], data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return {"sent": response.status < 300, "state": "SENT",
                    "status_code": response.status}
    except Exception as error:  # noqa: BLE001 - alerting must never crash a job
        return {"sent": False, "state": "ERROR", "error_type": type(error).__name__}
