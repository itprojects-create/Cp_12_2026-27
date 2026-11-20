"""Research-agent calibration plumbing (P6, §§57–62).

Records priors at proposal time, settles outcomes at maturity, and reports
Brier/reliability/overconfidence ONLY when the resolved sample justifies it
(n >= MIN_RESOLVED, else INSUFFICIENT_CALIBRATION_SAMPLE — never a fake score).

Priors are research metadata. No capital-path module may read them (isolation
test below scans money-path sources for calibration imports AND for the prior
field names).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import sqlite_conn

MIN_RESOLVED = 30
STAGES = ("backtest", "falsification", "shadow", "promotion")

# Outcome -> stage-survival truth (1 = survived that stage).
_TERMINAL_FAIL = {
    "backtest": {"FAILED_SCHEMA", "DUPLICATE", "REJECTED_SCHEMA", "FAILED_BACKTEST"},
    "falsification": {"FAILED_SCHEMA", "DUPLICATE", "REJECTED_SCHEMA", "FAILED_BACKTEST",
                      "FAILED_FALSIFICATION"},
    "shadow": {"SHADOW", "FORWARD_VALIDATING", "PROMOTED", "CHAMPION", "FAILED_FORWARD"},
    "promotion": {"PROMOTED", "CHAMPION"},
}
PRIOR_FIELDS = {"backtest": "estimated_probability_survives_backtest",
                "falsification": "estimated_probability_survives_falsification",
                "shadow": "estimated_probability_reaches_shadow",
                "promotion": "estimated_probability_reaches_promotion"}


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS research_predictions
        (hypothesis_fp TEXT PRIMARY KEY, role TEXT, p_backtest REAL,
         p_falsification REAL, p_shadow REAL, p_promotion REAL, ts TEXT)""")
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS research_outcomes
        (hypothesis_fp TEXT PRIMARY KEY, outcome TEXT, ts TEXT)""")
    sqlite_conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _priors_from(hypothesis: dict) -> dict:
    return {stage: hypothesis.get(field) for stage, field in PRIOR_FIELDS.items()}


def record_prediction(hypothesis_fp: str, role: str, hypothesis: dict) -> dict:
    """Lock priors at proposal time. First write wins (INSERT OR IGNORE) —
    hindsight edits are impossible by construction."""
    init_tables()
    priors = _priors_from(hypothesis)
    sqlite_conn().execute(
        "INSERT OR IGNORE INTO research_predictions(hypothesis_fp, role, p_backtest,"
        " p_falsification, p_shadow, p_promotion, ts) VALUES (?,?,?,?,?,?,?)",
        (hypothesis_fp, role, priors["backtest"], priors["falsification"],
         priors["shadow"], priors["promotion"], _now()))
    sqlite_conn().commit()
    row = sqlite_conn().execute(
        "SELECT role, p_backtest, p_falsification, p_shadow, p_promotion"
        " FROM research_predictions WHERE hypothesis_fp=?", (hypothesis_fp,)).fetchone()
    return {"hypothesis_fp": hypothesis_fp, "role": row[0],
            "priors": {"backtest": row[1], "falsification": row[2],
                       "shadow": row[3], "promotion": row[4]}}


def settle_prediction(hypothesis_fp: str, outcome: str) -> dict:
    """Terminal (or progressive) outcome. Replacement is state progression
    (pending -> terminal), recorded with timestamp."""
    init_tables()
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO research_outcomes(hypothesis_fp, outcome, ts)"
        " VALUES (?,?,?)", (hypothesis_fp, outcome, _now()))
    sqlite_conn().commit()
    return {"hypothesis_fp": hypothesis_fp, "outcome": outcome}


def _resolved() -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT p.hypothesis_fp, p.role, p.p_backtest, p.p_falsification, p.p_shadow,"
        " p.p_promotion, o.outcome FROM research_predictions p"
        " JOIN research_outcomes o ON p.hypothesis_fp=o.hypothesis_fp").fetchall()
    return [{"fp": r[0], "role": r[1],
             "priors": {"backtest": r[2], "falsification": r[3], "shadow": r[4],
                        "promotion": r[5]},
             "outcome": r[6]} for r in rows]


def _survived(stage: str, outcome: str) -> int | None:
    if stage in ("backtest", "falsification"):
        return 0 if outcome in _TERMINAL_FAIL[stage] else 1
    if stage == "shadow":
        return 1 if outcome in _TERMINAL_FAIL["shadow"] else 0
    if stage == "promotion":
        return 1 if outcome in _TERMINAL_FAIL["promotion"] else 0
    return None  # noqa: RET501 (unreachable)


def calibration_report(min_n: int = MIN_RESOLVED) -> dict:
    """Brier + reliability bins + over/underconfidence per stage (§60)."""
    rows = [r for r in _resolved()
            if all(r["priors"][s] is not None for s in STAGES)]
    if len(rows) < min_n:
        return {"status": "INSUFFICIENT_CALIBRATION_SAMPLE", "n": len(rows),
                "min_n": min_n}
    stages = {}
    for stage in STAGES:
        pairs = [(r["priors"][stage], _survived(stage, r["outcome"])) for r in rows]
        brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
        bins, over, under, n_over, n_under = [], 0.0, 0.0, 0, 0
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            bucket = [(p, y) for p, y in pairs if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
            if not bucket:
                bins.append({"bin": [lo, round(lo + 0.2, 1)], "n": 0,
                             "mean_p": None, "empirical": None})
                continue
            mp = sum(p for p, _ in bucket) / len(bucket)
            emp = sum(y for _, y in bucket) / len(bucket)
            bins.append({"bin": [lo, round(lo + 0.2, 1)], "n": len(bucket),
                         "mean_p": round(mp, 3), "empirical": round(emp, 3)})
            if mp > emp:
                over += (mp - emp) * len(bucket)
                n_over += len(bucket)
            elif emp > mp:
                under += (emp - mp) * len(bucket)
                n_under += len(bucket)
        stages[stage] = {"n": len(pairs), "brier": round(brier, 4), "bins": bins,
                         "overconfidence_rate": round(over / len(pairs), 4),
                         "underconfidence_rate": round(under / len(pairs), 4)}
    return {"status": "REPORTED", "n": len(rows), "stages": stages}


def role_value_metrics() -> dict:
    """Per-role research value (§61): volume, survival funnel, costs.
    Roles are compared on research output — never on asserted cleverness."""
    from app.research_memory import store as ST
    init_tables()
    ST.init_tables()
    roles: dict[str, dict] = {}
    for r in _resolved():
        m = roles.setdefault(r["role"], {"resolved": 0, "outcomes": {}})
        m["resolved"] += 1
        m["outcomes"][r["outcome"]] = m["outcomes"].get(r["outcome"], 0) + 1
    proposed: dict[str, int] = {}
    for p in sqlite_conn().execute(
            "SELECT role, COUNT(*) FROM research_predictions GROUP BY role").fetchall():
        proposed[p[0]] = p[1]
    costs: dict[str, float] = {}
    for fp, role in sqlite_conn().execute(
            "SELECT hypothesis_fp, role FROM research_predictions").fetchall():
        h = ST.get_hypothesis(fp)
        if h:
            costs[role] = costs.get(role, 0.0) + float(h["body"].get(
                "estimated_research_cost", 0.0) or 0.0)
    return {"by_role": {
        role: {"proposed": proposed.get(role, 0),
               "resolved": roles.get(role, {}).get("resolved", 0),
               "outcomes": roles.get(role, {}).get("outcomes", {}),
               "research_cost": round(costs.get(role, 0.0), 2)}
        for role in set(list(proposed) + list(roles))},
        "note": "research value only; capital-path isolation enforced by test"}


def comparison_frame(context_hash: str, memory_snapshot_hash: str, universe: str,
                     token_budget: int, experiment_budget: int,
                     evaluation_rules: str) -> dict:
    """Fairness manifest for model/prompt comparisons (§62): same frame or
    the comparison is invalid. Frame hash binds all inputs."""
    import hashlib as _h
    import json as _j
    frame = {"context_hash": context_hash, "memory_snapshot_hash": memory_snapshot_hash,
             "universe": universe, "token_budget": token_budget,
             "experiment_budget": experiment_budget, "evaluation_rules": evaluation_rules}
    frame["frame_hash"] = _h.sha256(
        _j.dumps(frame, sort_keys=True).encode()).hexdigest()[:16]
    return frame
