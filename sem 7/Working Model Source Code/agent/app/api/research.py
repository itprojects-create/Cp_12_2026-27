"""Research API namespace (migration §54). Additive; /api/v1 shapes unchanged.

Read-mostly audit surface over research memory + champion registry. The only
write paths validate-then-store (hypotheses, experiments) — no code execution,
no capital plumbing, no broker access. Dangerous arbitrary-code endpoints do
not exist here by design.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/research")


class HypothesisIn(BaseModel):
    hypothesis: dict
    new_evidence: str = ""


class ExperimentIn(BaseModel):
    hypothesis_fp: str
    body: dict
    status: str = "EXPERIMENTING"


@router.post("/hypotheses")
def submit_hypothesis(req: HypothesisIn):
    from app.research_memory import store as ST
    try:
        return ST.submit_hypothesis(req.hypothesis, new_evidence=req.new_evidence)
    except Exception as e:  # noqa: BLE001 - schema rejection is a 422, not a 500
        raise HTTPException(422, f"hypothesis rejected: {e}") from e


@router.get("/hypotheses")
def list_hypotheses(status: str | None = None):
    from app.research_memory import store as ST
    return {"hypotheses": ST.list_hypotheses(status=status)}


@router.get("/corpses")
def list_corpses():
    from app.research_memory import store as ST
    return {"corpses": [{k: c[k] for k in ("fp", "failure_reason", "evidence_required", "ts")}
                        for c in ST.list_corpses()]}


@router.get("/corpses/{fp}")
def corpse_detail(fp: str):
    from app.research_memory import retrieval as RET
    from app.research_memory import store as ST
    c = ST.get_corpse_by_fp(fp)
    if c is None:
        raise HTTPException(404, "corpse not found")
    return {**c, "match_block": RET.format_corpse_match(c.get("body", {}), c)}


@router.get("/champion")
def champion():
    from app.evo import champion as CH
    g = CH.get_champion()
    if g is None:
        raise HTTPException(404, "no champion registered")
    return g


@router.get("/challengers")
def challengers():
    from app.evo import champion as CH
    return {"challengers": CH.list_challengers()}


@router.get("/lineage/{fp}")
def lineage(fp: str, depth: int = 4):
    from app.research_memory import lineage as LIN
    return LIN.tree(fp, depth=min(depth, 8))


@router.post("/experiments")
def record_experiment(req: ExperimentIn):
    from app.research_memory import evidence as EV
    from app.research_memory import store as ST
    try:
        EV.build_evidence_record(hypothesis_id=req.body.get("hypothesis_id", "?"),
                                 hypothesis_fp=req.hypothesis_fp,
                                 creator_agent=req.body.get("creator_agent", "api"),
                                 strategy_fp=req.body.get("strategy_fp", "strat-pending"),
                                 parameter_fp=req.body.get("parameter_fp", "par-pending"),
                                 data_fp=req.body.get("data_fp", "data-pending"),
                                 data_status=req.body.get("data_status", "exploratory"),
                                 universe=req.body.get("universe", []),
                                 features=req.body.get("features", []),
                                 code_version=req.body.get("code_version", "unknown"),
                                 gateset=req.body.get("gateset", "GATESET_FROZEN_20260918"),
                                 benchmark=req.body.get("benchmark", "NIFTY50_TRI"),
                                 cost_model=req.body.get("cost_model", "env-v1"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"experiment": ST.record_experiment(req.hypothesis_fp, req.body, req.status)}


# --- P7 data-quality / audit surface (§§84-85). Read-only; no mutation
# endpoint here can alter live capital behavior (there is none to alter:
# research storage only). ---

@router.get("/data-registry")
def data_registry():
    from app.data import registry as REG
    REG.seed_known()
    return {"registry_version": REG.REGISTRY_VERSION,
            "datasets": REG.list_datasets()}


@router.get("/events")
def events(since: str = "2026-10-01", until: str = "2026-12-31"):
    from app.events import store as ST
    return {"events": ST.announcements_in_range(since, until)}


@router.get("/events/{record_id}")
def event_detail(record_id: str):
    from app.events import store as ST
    raw = ST.get_raw(record_id)
    if raw is None:
        raise HTTPException(404, "event not found")
    return {"raw": raw, "classifications": ST.classifications_for(record_id),
            "links": ST.links_for(record_id)}


@router.get("/pit/{universe}/{timestamp}")
def pit_snapshot(universe: str, timestamp: str):
    from app.data import pit_membership as PM
    if universe not in ("nifty50", "nifty500"):
        raise HTTPException(422, "universe must be nifty50|nifty500")
    try:
        snap = PM.membership_at(universe, timestamp, strict=False)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    return {"members": snap["members"][:50], "n_members": len(snap["members"]),
            "pit_status": snap["pit_status"], "coverage": snap["coverage"],
            "membership_hash": snap["membership_hash"],
            "membership_source_version": snap["membership_source_version"],
            "truncated": len(snap["members"]) > 50}


@router.get("/calibration")
def calibration():
    from app.research import calibration as CAL
    return {"calibration": CAL.calibration_report(),
            "roles": CAL.role_value_metrics()}


@router.get("/experiments/{exp_id}/evidence")
def experiment_evidence(exp_id: str):
    from app.db import sqlite_conn
    from app.research_memory import evidence as EV
    row = sqlite_conn().execute(
        "SELECT id, hypothesis_fp, body, status FROM research_experiments"
        " WHERE id=?", (exp_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "experiment not found")
    import json as _j
    return {"experiment": row[0], "status": row[3],
            "evidence": EV.manifest(row[0], _j.loads(row[2]))}
