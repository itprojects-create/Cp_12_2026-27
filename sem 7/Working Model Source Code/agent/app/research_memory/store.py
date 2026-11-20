"""Research-memory store: hypotheses, experiments, corpses, lineage (§8).

Tables (all in the shared SQLite ledger; tests are hermetic via QP_DB_PATH):
  research_hypotheses(fp PK, hypothesis_id, body, status, ts)
  research_experiments(id PK, hypothesis_fp, body, status, ts)
  research_corpses(fp PK, body, failure_reason, evidence_required, ts)
  research_lineage(child_fp PK, parent_fp, relation, ts)

Submit-time discipline: exact-fingerprint duplicates and corpse matches are
refused unless genuinely new evidence is supplied (R13). Near-duplicates are
surfaced, not silently stored.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import sqlite_conn
from app.governance.constitution import StrategyStatus
from app.research import fingerprints as FP
from app.research.schema import ResearchHypothesis

FAILURE_STATUSES = frozenset({
    StrategyStatus.FAILED_BACKTEST, StrategyStatus.FAILED_FALSIFICATION,
    StrategyStatus.FAILED_DSR, StrategyStatus.FAILED_PBO,
    StrategyStatus.FAILED_COST, StrategyStatus.FAILED_CONCENTRATION,
    StrategyStatus.FAILED_FORWARD,
})


def init_tables() -> None:
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS research_hypotheses
        (fp TEXT PRIMARY KEY, hypothesis_id TEXT, body TEXT, status TEXT, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS research_experiments
        (id TEXT PRIMARY KEY, hypothesis_fp TEXT, body TEXT, status TEXT, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS research_corpses
        (fp TEXT PRIMARY KEY, body TEXT, failure_reason TEXT,
         evidence_required TEXT, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS research_lineage
        (child_fp TEXT PRIMARY KEY, parent_fp TEXT, relation TEXT, ts TEXT)""")
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(sql: str, args: tuple = ()) -> dict | None:
    r = sqlite_conn().execute(sql, args).fetchone()
    if r is None:
        return None
    cols = [d[0] for d in sqlite_conn().execute(sql, args).description]
    return dict(zip(cols, r))


def get_hypothesis(fp_value: str) -> dict | None:
    r = _row("SELECT fp, hypothesis_id, body, status, ts FROM research_hypotheses WHERE fp=?",
             (fp_value,))
    if r:
        r["body"] = json.loads(r["body"])
    return r


def list_hypotheses(status: str | None = None) -> list[dict]:
    init_tables()
    sql = "SELECT fp, hypothesis_id, body, status, ts FROM research_hypotheses"
    args: tuple = ()
    if status:
        sql += " WHERE status=?"
        args = (status,)
    rows = sqlite_conn().execute(sql, args).fetchall()
    return [{"fp": r[0], "hypothesis_id": r[1], "body": json.loads(r[2]),
             "status": r[3], "ts": r[4]} for r in rows]


def submit_hypothesis(hypo: dict, new_evidence: str = "") -> dict:
    """Validate, fingerprint, dedup, corpse-check, store as PROPOSED.

    Returns {stored: bool, status, fp, note, prior?}. Refusals never raise —
    the orchestrator routes on status (DUPLICATE / DEAD_MATCH).
    """
    init_tables()
    h = ResearchHypothesis(**hypo).model_dump(mode="json")
    fp_value = FP.hypothesis_fingerprint(h)
    prior = get_hypothesis(fp_value)
    corpse = get_corpse_by_fp(fp_value)
    if prior is not None and StrategyStatus(prior["status"]) in FAILURE_STATUSES:
        # Failed before: resubmission must confront the corpse, not a bare DUPLICATE.
        if not new_evidence.strip():
            return {"stored": False, "status": "DEAD_MATCH",
                    "fp": fp_value,
                    "note": "idea failed before; new evidence required (R13)",
                    "corpse": corpse}
    elif prior is not None:
        return {"stored": False, "status": StrategyStatus.DUPLICATE.value,
                "fp": fp_value, "note": "exact fingerprint already stored",
                "prior": prior["hypothesis_id"]}
    if corpse is not None and not new_evidence.strip():
        return {"stored": False, "status": "DEAD_MATCH",
                "fp": fp_value, "note": "idea matches a prior corpse; new evidence required",
                "corpse": corpse}
    if prior is not None and new_evidence.strip():
        # Genuinely new evidence reopens the idea (status back to PROPOSED);
        # the corpse and lineage stay on record — history is not rewritten.
        sqlite_conn().execute("UPDATE research_hypotheses SET status=? WHERE fp=?",
                              (StrategyStatus.PROPOSED.value, fp_value))
        sqlite_conn().commit()
        return {"stored": True, "status": StrategyStatus.PROPOSED.value,
                "fp": fp_value, "note": "reopened on new evidence; corpse retained",
                "reopened": True}
    from app.research_memory import fingerprints as RFP
    near = RFP.near_duplicate(h, [x["body"] | {"hypothesis_id": x["hypothesis_id"]}
                                  for x in list_hypotheses()])
    sqlite_conn().execute(
        "INSERT INTO research_hypotheses(fp, hypothesis_id, body, status, ts)"
        " VALUES (?,?,?,?,?)",
        (fp_value, h["hypothesis_id"], json.dumps(h, sort_keys=True),
         StrategyStatus.PROPOSED.value, _now()))
    sqlite_conn().commit()
    rec: dict = {"stored": True, "status": StrategyStatus.PROPOSED.value,
                 "fp": fp_value, "note": "stored as PROPOSED"}
    if near is not None:
        rec["near_duplicate"] = {"hypothesis_id": near["match"].get("hypothesis_id"),
                                 "similarity": near["similarity"]}
    return rec


def record_experiment(hypothesis_fp: str, body: dict,
                      status: str = StrategyStatus.EXPERIMENTING.value) -> str:
    """Store an experiment record (§8 fields carried in body). Returns exp id."""
    init_tables()
    n = sqlite_conn().execute("SELECT COUNT(*) FROM research_experiments").fetchone()[0]
    exp_id = f"EXP-{n + 1:05d}"
    sqlite_conn().execute(
        "INSERT INTO research_experiments(id, hypothesis_fp, body, status, ts)"
        " VALUES (?,?,?,?,?)",
        (exp_id, hypothesis_fp, json.dumps(body, sort_keys=True), status, _now()))
    sqlite_conn().commit()
    return exp_id


def record_outcome(exp_id: str, status: str, metrics: dict | None = None,
                   failure_reason: str = "", evidence_required: str = "") -> dict:
    """Terminal transition for an experiment. Failure statuses bury a corpse."""
    from app.research_memory import corpses as CORP
    init_tables()
    sqlite_conn().execute("UPDATE research_experiments SET status=? WHERE id=?",
                          (status, exp_id))
    sqlite_conn().commit()
    rec: dict = {"experiment": exp_id, "status": status}
    if StrategyStatus(status) in FAILURE_STATUSES:
        exp = _row("SELECT id, hypothesis_fp, body FROM research_experiments WHERE id=?",
                   (exp_id,))
        hypo_fp = exp["hypothesis_fp"] if exp else ""
        if hypo_fp:
            # The hypothesis itself carries the failure status so resubmission
            # confronts the corpse (R13) instead of a bare DUPLICATE.
            sqlite_conn().execute("UPDATE research_hypotheses SET status=? WHERE fp=?",
                                  (status, hypo_fp))
            sqlite_conn().commit()
        hypo = get_hypothesis(hypo_fp)
        rec["corpse"] = CORP.bury(
            fp_value=hypo_fp or f"exp-{exp_id}",
            idea=(hypo["body"] if hypo else {"experiment": exp_id}),
            failure_reason=failure_reason or status,
            metrics=metrics or {},
            evidence_required=evidence_required)
    return rec


def get_corpse_by_fp(fp_value: str) -> dict | None:
    init_tables()
    r = _row("SELECT fp, body, failure_reason, evidence_required, ts FROM research_corpses"
             " WHERE fp=?", (fp_value,))
    if r:
        r["body"] = json.loads(r["body"])
    return r


def list_corpses() -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT fp, body, failure_reason, evidence_required, ts FROM research_corpses").fetchall()
    return [{"fp": r[0], "body": json.loads(r[1]), "failure_reason": r[2],
             "evidence_required": r[3], "ts": r[4]} for r in rows]
