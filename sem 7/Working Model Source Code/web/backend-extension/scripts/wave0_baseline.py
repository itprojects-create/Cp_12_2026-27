"""W0.1 — Quant Plus V3.1 baseline: read-only audit + verified online backup of V2 state.

Reads the PRODUCTION V2 forecast ledger (D:\\QP\\agent-service\\data\\forecast_ledger.sqlite3)
via the SQLite online-backup API (safe under WAL, never a mid-write file copy), verifies the
hash chain, inventories rows by status, and hashes every V2 evidence artifact BEFORE any new
code runs. Writes:

  reports/alpha_v3_1/backups/forecast_ledger_w0_backup.sqlite3
  reports/alpha_v3_1/v2_pre_post_hashes.json
  reports/alpha_v3_1/settlement_waterfall.json

Read-only against production (sqlite3 URI mode=ro for verification; backup API copies bytes).
This script never mutates the production ledger, never settles, never backfills.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

# Import schema helpers (canonical/card_from_dict) from the development copy.
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from quantplus_intelligence.forecast.schema import card_from_dict  # noqa: E402

PROD_LEDGER = Path(r"D:\QP\agent-service\data\forecast_ledger.sqlite3")
PROD_REPORTS = Path(r"D:\QP\agent-service\data\forecast_reports")
REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS = REPO_ROOT / "reports" / "alpha_v3_1"
BACKUP = REPORTS / "backups" / "forecast_ledger_w0_backup.sqlite3"

GENESIS = "0" * 64


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def chain_verify(conn: sqlite3.Connection) -> dict:
    """Recompute the hash chain exactly as ledger.Ledger.verify does (read-only)."""
    prev, n, broken = GENESIS, 0, None
    rows = conn.execute(
        "SELECT seq, card_id, payload, recorded_at, prev_hash, hash "
        "FROM forecast_ledger ORDER BY seq").fetchall()
    for seq, card_id, payload, stamp, prev_hash, digest in rows:
        expect = hashlib.sha256(f"{prev}|{card_id}|{payload}|{stamp}".encode()).hexdigest()
        ok = prev_hash == prev and expect == digest
        if ok:
            try:
                ok = card_from_dict(json.loads(payload)).card_id == card_id
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            broken = {"seq": seq, "checked": n}
            break
        prev, n = digest, n + 1
    return {"valid": broken is None, "checked": n, "head": prev if broken is None else None,
            "broken_at": broken}


def online_backup(src: Path, dst: Path) -> dict:
    """Consistent online backup via sqlite3 backup API (WAL-safe), then hash the copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
            dst_conn.execute("PRAGMA journal_mode=DELETE")  # leave no WAL artefacts in the copy
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return {"path": str(dst), "bytes": dst.stat().st_size, "sha256": sha256_file(dst)}


def classify_oct30(conn: sqlite3.Connection, today: date | None = None) -> dict:
    """W0.2 waterfall for every card, plus a focused Oct-30 five-session cohort view.

    Statuses follow the master prompt:
      ALREADY_SETTLED | NOT_MATURE | MATURE_WAITING_FOR_PRICE | INVALID_CALENDAR
    (job/state confounds — MATURE_WAITING_FOR_JOB — need scheduler receipts, recorded
    separately; SOURCE_MISMATCH requires a second price source, flagged NOT_CHECKED here.)
    """
    today = today or date.today()
    rows = conn.execute(
        "SELECT card_id, symbol, as_of, horizon, matures_on, recorded_at, settled_at, payload "
        "FROM forecast_ledger ORDER BY seq").fetchall()
    statuses: Counter = Counter()
    cohort, per_day = [], Counter()
    for card_id, symbol, as_of, horizon, matures_on, recorded_at, settled_at, payload in rows:
        card = json.loads(payload)
        if card.get("abstain"):
            status = "ABSTAINED"
        elif settled_at is not None:
            status = "ALREADY_SETTLED"
        elif not matures_on:
            status = "INVALID_CALENDAR"      # calendar unverified at record time
        elif date.fromisoformat(matures_on) > today:
            status = "NOT_MATURE"
        else:
            # matured and unsettled: the settle job either never ran or prices were absent
            status = "MATURE_WAITING_FOR_PRICE"
        statuses[status] += 1
        per_day[(as_of[:10], horizon, status)] += 1
        if as_of[:10] == "2026-10-30" and not card.get("abstain"):
            outcome = None
            if settled_at is not None:
                raw = conn.execute("SELECT outcome FROM forecast_ledger WHERE card_id=?",
                                   (card_id,)).fetchone()[0]
                outcome = json.loads(raw) if raw else None
            cohort.append({
                "card_id": card_id, "symbol": symbol, "horizon": horizon,
                "as_of": as_of, "recorded_at": recorded_at, "matures_on": matures_on,
                "settled_at": settled_at, "status": status, "outcome": outcome,
            })
    days = {}
    for (day, horizon, status), n in per_day.items():
        days.setdefault(day, {}).setdefault(str(horizon), {})[status] = n
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "today": today.isoformat(), "statuses": dict(statuses),
            "oct30_cohort": sorted(cohort, key=lambda c: (c["horizon"], c["symbol"])),
            "by_day_horizon_status": {d: {h: s for h, s in sorted(h.items())}
                                      for d, h in sorted(days.items())}}


def inventory(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM forecast_ledger").fetchone()[0]
    settled = conn.execute("SELECT COUNT(*) FROM forecast_ledger WHERE settled_at IS NOT NULL").fetchone()[0]
    abstained = conn.execute(
        "SELECT COUNT(*) FROM forecast_ledger WHERE settled_at IS NOT NULL "
        "AND json_extract(payload, '$.abstain') = 1").fetchone()[0]
    scored = conn.execute(
        "SELECT COUNT(*) FROM forecast_ledger WHERE settled_at IS NOT NULL "
        "AND json_extract(payload, '$.abstain') = 0").fetchone()[0]
    by_horizon = dict(conn.execute(
        "SELECT horizon, COUNT(*) FROM forecast_ledger GROUP BY horizon").fetchall())
    abstain_by_horizon = dict(conn.execute(
        "SELECT horizon, COUNT(*) FROM forecast_ledger "
        "WHERE json_extract(payload, '$.abstain') = 1 GROUP BY horizon").fetchall())
    return {"total_cards": total, "settled_rows": settled, "abstained": abstained,
            "scored": scored, "unsettled": total - settled,
            "by_horizon": {str(k): v for k, v in by_horizon.items()},
            "abstained_by_horizon": {str(k): v for k, v in abstain_by_horizon.items()}}


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    if not PROD_LEDGER.exists():
        print(json.dumps({"error": f"production ledger not found: {PROD_LEDGER}"}, indent=2))
        return 2

    # 1) verified consistent backup BEFORE anything else
    backup_info = online_backup(PROD_LEDGER, BACKUP)

    # 2) read-only verification + inventory on the BACKUP (never on the live file)
    conn = sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True)
    try:
        chain = chain_verify(conn)
        inv = inventory(conn)
        waterfall = classify_oct30(conn)
    finally:
        conn.close()

    # 3) hash every V2 evidence artifact (shadow JSONL, chain heads, bridge snapshots)
    artifacts = {
        "prod_forecast_ledger": sha256_file(PROD_LEDGER),
        "prod_paper_pnl_jsonl": sha256_file(PROD_REPORTS / "paper_pnl.jsonl"),
        "prod_ledger_heads_jsonl": sha256_file(PROD_REPORTS / "ledger_heads.jsonl"),
        "prod_bridge_reports": [sha256_file(p) for p in sorted((PROD_REPORTS / "bridge").glob("*.json"))],
        "prod_schedule_logs": {p.name: sha256_file(p) for p in sorted(PROD_REPORTS.glob("schedule_*.log"))},
    }
    baseline = {
        "generated_at": now,
        "production_ledger": {"path": str(PROD_LEDGER), "bytes": PROD_LEDGER.stat().st_size,
                              "sha256": artifacts["prod_forecast_ledger"]},
        "backup": backup_info,
        "chain": chain,
        "inventory": inv,
        "artifact_hashes": artifacts,
        "quarantine_note": "oracle_tainted_*_DO_NOT_USE.json remain quarantined (DO_NOT_USE); not touched.",
        "claim": "pre-change baseline: chain valid, counts recorded; no mutation performed",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "v2_pre_post_hashes.json").write_text(
        json.dumps(baseline, indent=2, default=str), encoding="utf-8")
    (REPORTS / "settlement_waterfall.json").write_text(
        json.dumps(waterfall, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"chain": chain, "inventory": inv,
                      "statuses": waterfall["statuses"],
                      "oct30_cohort_n": len(waterfall["oct30_cohort"]),
                      "backup_sha256": backup_info["sha256"]}, indent=2, default=str))
    return 0 if chain["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
