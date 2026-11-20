"""Evening refresh watcher: finish the week-results workbook once the daily batch locks.

For Fri Nov 6, 2026: the scheduled 16:30 daily locks Batch D against the completed
Nov 5 bar. This watcher polls the ledger until that batch is present (>= 190 of the
200 expected cards), then runs the pre-registered paper stream ONCE (idempotent —
the 21:00 catch-up sees 'batch already picked') and regenerates the workbook with
the Nov 6 closes, the first shadow picks and the Friday Jobs-Log facts.

If the batch is still partial by 17:25, it skips the picks (the 21:00 catch-up
completes the batch against the same bar and picks it there) and regenerates the
workbook anyway with an honest empty Paper tab. It never backfills prices or
creates fabricated rows; reads are sqlite read-only.
"""
import json
import sqlite3
import subprocess
import time
from datetime import datetime, time as dtime
from pathlib import Path

PY = Path(r"D:\Quant-Plus\.local-data\backend-runtime\Scripts\python.exe")
BACKEND = Path(r"D:\QP\agent-service")
REPO = Path(r"D:\Quant-Plus")
LEDGER = BACKEND / "data" / "forecast_ledger.sqlite3"
STATUS = REPO / "reports" / "evening-refresh-status.json"
BATCH_AS_OF = "2026-11-05T00:00:00+00:00"
MIN_COMPLETE = 190      # tolerate <= 5 Yahoo-side symbol gaps in a 100-symbol batch


def log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def batch_count() -> int:
    conn = sqlite3.connect(f"file:{LEDGER.as_posix()}?mode=ro", uri=True)
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM forecast_ledger WHERE as_of=?", (BATCH_AS_OF,)).fetchone()
        return int(n)
    finally:
        conn.close()


def run(cmd: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess:
    out = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        log(f"rc={out.returncode} for '{cmd[-1]}'\nSTDERR tail: {out.stderr[-500:]}")
    return out


def paper() -> dict:
    out = run([str(PY), "-B", "-m", "quantplus_intelligence.forecast.jobs", "paper"], BACKEND, 600)
    report = {"rc": out.returncode, "picked": None, "error": None}
    try:
        payload = json.loads(out.stdout)
        report["picked"] = payload.get("picked")
        report["batch_as_of"] = payload.get("batch_as_of")
        report["picks"] = payload.get("picks")
    except (json.JSONDecodeError, ValueError) as error:
        report["error"] = f"{type(error).__name__}: {out.stdout[-300:]}"
    (BACKEND / "data" / "forecast_reports" / "paper_manual_2026-11-06.log").write_text(
        out.stdout + "\n" + out.stderr, encoding="utf-8")
    return report


def export() -> dict:
    out = run([str(PY), "-B", "scripts/export-week-results.py"], REPO, 900)
    return {"rc": out.returncode, "tail": out.stdout[-400:]}


def main() -> int:
    log("watcher up — sleeping to the 16:35 poll window")
    first_poll = datetime.combine(datetime.now().date(), dtime(16, 35))
    deadline = datetime.combine(datetime.now().date(), dtime(17, 25))
    while datetime.now() < first_poll:
        time.sleep(60)

    cards, complete = -1, False
    while datetime.now() <= deadline:
        cards = batch_count()
        log(f"Batch D cards so far: {cards}")
        if cards >= MIN_COMPLETE:
            complete = True
            break
        time.sleep(120)

    log("poll done — batch complete: " + str(complete))
    picks = {"skipped": True, "reason": "batch incomplete by the deadline; the 21:00 catch-up picks it"} if not complete else None
    if complete:
        picks = paper()
        log(f"paper result: picked={picks.get('picked')}")
    export_out = export()
    log(f"export rc={export_out['rc']}")
    STATUS.write_text(json.dumps({
        "at": datetime.now().isoformat(),
        "batch_as_of": BATCH_AS_OF, "batch_cards": cards, "batch_complete": complete,
        "paper": picks, "export": export_out,
    }, indent=2), encoding="utf-8")
    return 0 if export_out["rc"] == 0 else export_out["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
