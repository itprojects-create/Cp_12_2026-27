"""Scheduler entrypoints: OS-neutral job registry (§52).

No framework: named jobs + collection windows + one-line scheduler
instructions (cron / Windows Task Scheduler). Collectors stay
scheduler-independent; jobs are idempotent by checkpoints + content hashes.
"""
from __future__ import annotations

WINDOWS = ("INTRADAY_EVENTS", "POST_CLOSE_MARKET", "POST_SETTLEMENT",
           "WEEKLY_FORWARD", "WEEKLY_RECONCILIATION", "DAILY_HEALTH",
           "DAILY_SNAPSHOT", "BACKUP", "MONTHLY_AUDIT")

JOBS: dict[str, dict] = {
    "daily_market": {"window": "POST_CLOSE_MARKET", "script": "scripts/run_job.py --job post-close",
                     "cadence": "daily 19:00 IST",
                     "cron": "30 13 * * 1-5", "datasets": ["equity-eod", "delivery", "indices"]},
    "announcements": {"window": "INTRADAY_EVENTS", "script": "scripts/run_job.py --job intraday-events",
                      "cadence": "every 30 min, trading days 09:30-16:00 IST",
                      "cron": "*/30 4-10 * * 1-5", "datasets": ["nse-announcements", "bse-announcements"]},
    "settlement": {"window": "POST_SETTLEMENT", "script": "scripts/run_job.py --job settlement",
                   "cadence": "daily 21:00 IST",
                   "cron": "30 15 * * 1-5", "datasets": ["bulk-block", "fii-dii", "fno", "corp-actions"]},
    "weekly_forward": {"window": "WEEKLY_FORWARD", "script": "scripts/forward_week.py",
                       "cadence": "Friday after close",
                       "cron": "30 13 * * 5", "datasets": ["forward-clock"]},
    "weekly_recon": {"window": "WEEKLY_RECONCILIATION",
                     "script": "python scripts/data_health.py && python scripts/audit_event_store.py",
                     "cadence": "Sunday 10:00 IST",
                     "cron": "30 4 * * 0", "datasets": ["all"]},
    "daily_health": {"window": "DAILY_HEALTH", "script": "scripts/quantplus_health.py",
                     "cadence": "daily 21:30 IST",
                     "cron": "0 16 * * *", "datasets": ["all"]},
    "daily_snapshot": {"window": "DAILY_SNAPSHOT", "script": "scripts/freeze_data_snapshot.py",
                       "cadence": "daily with post-close",
                       "cron": "45 13 * * 1-5", "datasets": ["all"]},
    "backup": {"window": "BACKUP", "script": "scripts/backup_evidence.py",
               "cadence": "daily 22:00 IST + weekly full Sunday",
               "cron": "0 16 * * *", "datasets": ["forward-evidence"]},
    "monthly_audit": {"window": "MONTHLY_AUDIT", "script": "scripts/monthly_audit.py",
                      "cadence": "1st Sunday 10:00 IST",
                      "cron": "30 4 * * 0", "datasets": ["all"]},
}


def instructions() -> str:
    lines = ["QuantPlus collection schedule (OS-neutral; collectors are idempotent):", ""]
    for name, job in JOBS.items():
        lines.append(f"[{job['window']}] {name}: {job['cadence']}")
        lines.append(f"  cron: {job['cron']}  ->  {job['script']}")
        lines.append(f"  Task Scheduler: daily/weekly trigger matching cadence above.")
    lines.append("")
    lines.append("Windows Task Scheduler example (daily_market):")
    lines.append('  schtasks /create /tn QP-daily-market /tr "python scripts/update_market_data.py"'
                 ' /sc weekly /d MON,TUE,WED,THU,FRI /st 19:00')
    return "\n".join(lines)
