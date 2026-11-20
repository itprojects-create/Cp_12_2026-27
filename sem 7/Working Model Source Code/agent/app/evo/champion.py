"""Champion / challenger registry (migration §17).

The champion stays until a challenger passes the versioned promotion gate on
forward evidence — never on one strong week (the gate's MIN_FORWARD_N is the
stabilizer). Genesis champion is the deterministic v4 core, registered with
its historical record and an explicit pre-forward caveat.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import sqlite_conn
from app.evo import promotion as PROM
from app.evo import store as ST
from app.governance.constitution import StrategyStatus

GENESIS_NOTE = ("genesis champion: deterministic v4 core (HISTORICALLY_SURVIVED "
                "on blind 2015-2020); must survive the forward clock or retire (R8)")


def init_tables() -> None:
    ST.init()
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS strategy_pool
        (fp TEXT PRIMARY KEY, name TEXT, status TEXT, evidence TEXT, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS champion_history
        (id INTEGER PRIMARY KEY AUTOINCREMENT, fp TEXT, since TEXT,
         retired_at TEXT, retirement_reason TEXT, promotion_evidence TEXT)""")
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_candidate(fp_value: str, name: str, evidence: dict,
                       status: str = StrategyStatus.SHADOW.value) -> dict:
    init_tables()
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO strategy_pool(fp, name, status, evidence, ts)"
        " VALUES (?,?,?,?,?)",
        (fp_value, name, status, json.dumps(evidence, sort_keys=True, default=str),
         _now()))
    sqlite_conn().commit()
    return {"fp": fp_value, "name": name, "status": status}


def pool_status(fp_value: str) -> dict | None:
    init_tables()
    r = sqlite_conn().execute(
        "SELECT fp, name, status, evidence, ts FROM strategy_pool WHERE fp=?",
        (fp_value,)).fetchone()
    if not r:
        return None
    return {"fp": r[0], "name": r[1], "status": r[2],
            "evidence": json.loads(r[3]), "ts": r[4]}


def get_champion() -> dict | None:
    init_tables()
    r = sqlite_conn().execute(
        "SELECT fp, since, promotion_evidence FROM champion_history"
        " WHERE retired_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    info = pool_status(r[0]) or {"fp": r[0], "name": r[0], "status": "CHAMPION"}
    return {**info, "champion_since": r[1], "promotion_evidence": json.loads(r[2])}


def list_challengers() -> list[dict]:
    """Pool entries that are neither champion, retired, nor dead."""
    init_tables()
    champ = get_champion()
    champ_fp = champ["fp"] if champ else None
    rows = sqlite_conn().execute(
        "SELECT fp, name, status FROM strategy_pool").fetchall()
    return [{"fp": r[0], "name": r[1], "status": r[2]} for r in rows
            if r[0] != champ_fp and r[2] not in ("RETIRED", "DEAD")]


def set_genesis(fp_value: str, name: str, evidence: dict) -> dict:
    """Register the pre-forward champion once (idempotent)."""
    init_tables()
    if get_champion() is not None:
        return get_champion()
    register_candidate(fp_value, name, evidence, StrategyStatus.CHAMPION.value)
    sqlite_conn().execute(
        "INSERT INTO champion_history(fp, since, retired_at, retirement_reason,"
        " promotion_evidence) VALUES (?,?,?,?,?)",
        (fp_value, _now(), None, "",
         json.dumps({"genesis": GENESIS_NOTE, **evidence}, sort_keys=True,
                    default=str)))
    sqlite_conn().commit()
    return get_champion()


def promote(challenger_fp: str, evidence: dict,
            gateset: str = PROM.VERSION) -> dict:
    """Deterministic promotion (R5): gate decides, code executes. Returns the
    verdict record; on success the incumbent retires as superseded.

    gateset="auto" dispatches on evidence["evidence_class"] (ALPHA default for
    legacy packs): alpha/risk/execution/quality gates per §§47-51."""
    init_tables()
    if gateset == "auto":
        from app.evo import evidence_gates as EG
        gate = EG.check_by_class(evidence.get("evidence_class", "ALPHA"), evidence)
    else:
        gate = PROM.check(evidence, gateset)
    if not gate["eligible"]:
        return {"promoted": False, "challenger": challenger_fp,
                "failures": gate["failures"], "warnings": gate["warnings"],
                "gateset": gate.get("gateset", gateset),
                "verdict": gate.get("verdict", "KILLED")}
    champ = get_champion()
    if champ is not None:
        sqlite_conn().execute(
            "UPDATE champion_history SET retired_at=?, retirement_reason=? WHERE fp=?"
            " AND retired_at IS NULL",
            (_now(), f"superseded by {challenger_fp} under {gateset}", champ["fp"]))
        sqlite_conn().execute("UPDATE strategy_pool SET status=? WHERE fp=?",
                              (StrategyStatus.RETIRED.value, champ["fp"]))
    cand = pool_status(challenger_fp) or {"name": challenger_fp}
    register_candidate(challenger_fp, cand["name"], evidence,
                       StrategyStatus.CHAMPION.value)
    sqlite_conn().execute(
        "INSERT INTO champion_history(fp, since, retired_at, retirement_reason,"
        " promotion_evidence) VALUES (?,?,?,?,?)",
        (challenger_fp, _now(), None, "",
         json.dumps(evidence, sort_keys=True, default=str)))
    sqlite_conn().commit()
    return {"promoted": True, "challenger": challenger_fp,
            "retired": champ["fp"] if champ else None,
            "warnings": gate["warnings"], "gateset": gate.get("gateset", gateset),
            "verdict": gate.get("verdict", "ALPHA_PASS")}


def retire(fp_value: str, reason: str) -> dict:
    init_tables()
    sqlite_conn().execute("UPDATE strategy_pool SET status=? WHERE fp=?",
                          (StrategyStatus.RETIRED.value, fp_value))
    sqlite_conn().execute(
        "UPDATE champion_history SET retired_at=?, retirement_reason=? WHERE fp=?"
        " AND retired_at IS NULL", (_now(), reason, fp_value))
    sqlite_conn().commit()
    ST._log_event(fp_value, "champion-retired", reason)
    return {"fp": fp_value, "status": "RETIRED", "reason": reason}
