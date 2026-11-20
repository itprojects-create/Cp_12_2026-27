"""Multiple-testing ledger: every strategy trial counts, dead ones included (§54).

Append-only: this module exposes record/seed/count/list — NO update or delete
primitives exist (a test asserts their absence). The count never decreases
because rows are never removed and re-registration is idempotent per trial_id.

Families: "return" (Sharpe-claim trials feeding DSR) vs "research" (accuracy /
ablation reads informing the null, Sharpe unknown). DSR consumes return-family
Sharpes; the honest-trial principle (§53: never undercount) is served by
seeding the full documented search history below.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import sqlite_conn
from app.eval import dsr as DSR

REGISTRY_VERSION = "DSR_REGISTRY_V1"

# Documented search history (seeded once, idempotent). Return-family Sharpes
# mirror dsr.TRIALS; research-family rows carry sharpe=None (different claim
# family — counted for honesty, excluded from the Sharpe null).
SEED_TRIALS: tuple[tuple[str, str, float | None, str], ...] = (
    *((f"hist-{name}", "return", sharpe, f"dsr.TRIALS via {src}")
      for name, sharpe, src in DSR.TRIALS),
    ("hist-direction-v1v5", "research", None, "7 official direction FAILs (accuracy family)"),
    ("hist-direction-v3rd", "research", None, "4 v3rd-window direction FAILs"),
    ("hist-retry-m10", "research", None, "retry-m10 FAIL, reliably-wrong p=0.002"),
    ("hist-h1-trend", "research", None, "H1 trend-direction FAIL 0.111"),
    ("hist-deviloff", "research", None, "devil-off ablation (holds everything)"),
    ("hist-ablation-overlay", "research", None, "overlay A/B/C: OFF on 360 cached decisions"),
)


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS eval_trials
        (trial_id TEXT PRIMARY KEY, family TEXT, sharpe REAL, outcome TEXT,
         status TEXT, note TEXT, ts TEXT)""")
    sqlite_conn().commit()


def record_trial(trial_id: str, family: str, sharpe: float | None,
                 outcome: str = "", status: str = "done",
                 note: str = "") -> dict:
    """Idempotent per trial_id: re-registration returns the existing row
    (same experiment cannot double-register, §78)."""
    init_tables()
    if family not in ("return", "research"):
        raise ValueError(f"unknown trial family {family!r}")
    row = sqlite_conn().execute(
        "SELECT trial_id, family, sharpe, outcome, status FROM eval_trials WHERE trial_id=?",
        (trial_id,)).fetchone()
    if row:
        return {"trial_id": row[0], "family": row[1], "sharpe": row[2],
                "outcome": row[3], "status": row[4], "duplicate": True}
    sqlite_conn().execute(
        "INSERT INTO eval_trials(trial_id, family, sharpe, outcome, status, note, ts)"
        " VALUES (?,?,?,?,?,?,?)",
        (trial_id, family, sharpe, outcome, status, note[:300],
         datetime.now(timezone.utc).isoformat()))
    sqlite_conn().commit()
    return {"trial_id": trial_id, "family": family, "sharpe": sharpe,
            "outcome": outcome, "status": status, "duplicate": False}


def seed_historical() -> dict:
    """Insert the documented search history. Idempotent; returns counts."""
    added = dupes = 0
    for tid, fam, sharpe, note in SEED_TRIALS:
        r = record_trial(tid, fam, sharpe, outcome="HISTORICAL",
                         status="done", note=note)
        if r["duplicate"]:
            dupes += 1
        else:
            added += 1
    return {"added": added, "duplicates": dupes, "total": trial_count()}


def trial_count(family: str | None = None) -> int:
    init_tables()
    if family:
        return sqlite_conn().execute(
            "SELECT COUNT(*) FROM eval_trials WHERE family=?", (family,)).fetchone()[0]
    return sqlite_conn().execute("SELECT COUNT(*) FROM eval_trials").fetchone()[0]


def return_sharpes() -> list[float]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT sharpe FROM eval_trials WHERE family='return' AND sharpe IS NOT NULL"
        " ORDER BY trial_id").fetchall()
    return [r[0] for r in rows]


def list_trials() -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT trial_id, family, sharpe, outcome, status, note, ts FROM eval_trials"
        " ORDER BY trial_id").fetchall()
    return [{"trial_id": r[0], "family": r[1], "sharpe": r[2], "outcome": r[3],
             "status": r[4], "note": r[5], "ts": r[6]} for r in rows]


def dsr_report(strategy_id: str, strategy_fingerprint: str, tested_period: str,
               observed_sharpe: float, t_obs: int, skew: float, kurtosis: float,
               selection_history: list[str] | None = None) -> dict:
    """Full DSR registry record (§53): trial history is explicit, p-value shown
    alongside DSR (both, never collapsed into one 'validated' label)."""
    sharpes = return_sharpes() or [s for _, s, _ in DSR.TRIALS]
    n_trials = trial_count("return") or len(sharpes)
    base = DSR.dsr(observed_sharpe, t_obs, skew, kurtosis, sharpes)
    return {"strategy_id": strategy_id, "strategy_fingerprint": strategy_fingerprint,
            "tested_period": tested_period, "number_of_trials": n_trials,
            "selection_history": selection_history or [t["trial_id"] for t in list_trials()
                                                       if t["family"] == "return"],
            "observed_sharpe": observed_sharpe, "t_obs": t_obs,
            "skew": round(skew, 4), "kurtosis": round(kurtosis, 4),
            "expected_max_sharpe": base["sr0_null"], "deflated_sharpe": base["dsr"],
            "p_value": round(1 - base["dsr"], 4),
            "registry_version": REGISTRY_VERSION}
