"""Agentic research orchestrator (migration §9).

One cycle: OBSERVE -> RETRIEVE -> HYPOTHESIZE -> DEDUP -> FALSIFY-conceptually ->
PRIORITIZE -> COMPILE -> QUEUE EXPERIMENTS (+ manifests) -> LEDGER.

No LLM calls inside: hypothesis generation is an injected callable (in
production it wraps role prompts + gateway; in tests a deterministic stub).
Deterministic stages (validate, dedup, falsify-plan, prioritize, compile, manifest,
ledger) always run in code — cheaply and reproducibly. Backtest/shadow/forward
execution belongs to the arena/foundry; the orchestrator emits the queue, never
executes capital-adjacent work.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone

from app.research import fingerprints as FP

SPECIALIST_ROLES = ("factor", "microstructure", "regime_risk",
                    "event_fundamental", "failure_analysis")


def _code_commit() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - manifest records, never crashes
        return "unknown"


def run_cycle(query: str,
              propose_fn: Callable[[str, dict], list[dict]],
              dataset: str = "forward-from-2026-10-10",
              gateset: str = "GATESET_FROZEN_20260918",
              manifest_dir: str = "data/experiments",
              max_experiments: int = 3) -> dict:
    """Execute one research cycle. propose_fn(role, brief) -> hypothesis dicts.
    Returns the cycle record (briefs, submissions, plans, queue, manifests, ledger)."""
    from app.research import director as DIR
    from app.research import falsifier as FALS
    from app.research import specialists as SPEC
    from app.research.schema import ExperimentProposal, FalsificationPlan
    from app.research_memory import store as ST
    from app.foundry import dsl as DSL

    cycle_ts = datetime.now(timezone.utc).isoformat()
    briefs = {role: SPEC.specialist_brief(role, query) for role in SPECIALIST_ROLES}

    raw: list[tuple[str, dict]] = []
    raw_by_id: dict[str, dict] = {}
    for role, brief in briefs.items():
        try:
            hypos = propose_fn(role, brief) or []
        except Exception as e:  # noqa: BLE001 - a failing role must not kill the cycle
            hypos = []
            brief["role_error"] = f"{type(e).__name__}: {e}"
        for h in hypos:
            raw.append((role, h))
            # Raw dict retained: the stored body drops extra keys (e.g. an
            # embedded "dsl" program), which COMPILE still needs.
            if isinstance(h, dict) and h.get("hypothesis_id"):
                raw_by_id.setdefault(h["hypothesis_id"], h)

    submissions, rejected_schema = [], []
    for role, h in raw:
        try:
            rec = ST.submit_hypothesis(h)
            submissions.append({"role": role, **rec,
                                "hypothesis_id": h.get("hypothesis_id")})
        except Exception as e:  # noqa: BLE001 - schema rejection is routing, not crash
            rejected_schema.append({"role": role,
                                    "hypothesis_id": h.get("hypothesis_id"),
                                    "error": str(e)})

    stored_fps = [s["fp"] for s in submissions if s.get("stored")]
    plans = {}
    for s in submissions:
        if not s.get("stored"):
            continue
        hypo = ST.get_hypothesis(s["fp"])["body"]
        plans[s["fp"]] = FALS.plan_for(hypo.get("strategy_family", "veto_filter"))

    proposals = []
    for s in submissions:
        if not s.get("stored"):
            continue
        hypo = ST.get_hypothesis(s["fp"])["body"]
        plan = plans[s["fp"]]
        proposals.append(ExperimentProposal(
            hypothesis_id=hypo["hypothesis_id"],
            falsification_plan=FalsificationPlan(
                hypothesis_id=hypo["hypothesis_id"], tests=list(plan["required"]),
                kill_criteria=list(plan["kill_criteria"]),
                max_research_cost=float(hypo.get("estimated_research_cost", 0.0))),
            dataset=dataset, gateset=gateset,
            expected_information_gain=float(hypo.get("expected_information_gain", 1.0)),
            research_cost=float(hypo.get("estimated_research_cost", 0.0)),
            rationale=f"Cycle queue: {hypo.get('title', s['fp'])[:120]}"))

    queued = DIR.prioritize(proposals)[:max_experiments]

    manifests, experiments = [], []
    for p in queued:
        body = {"hypothesis_fp": _fp_of(p.hypothesis_id),
                "dataset": p.dataset, "gateset": p.gateset,
                "falsification_tests": p.falsification_plan.tests,
                "research_cost": p.research_cost}
        exp_id = ST.record_experiment(_fp_of(p.hypothesis_id), body)
        path = write_manifest(exp_id, p, dataset, gateset, manifest_dir)
        manifests.append(path)
        experiments.append(exp_id)

    # COMPILE: hypotheses carrying a dsl program compile now (deterministic).
    # The program rides on the raw submitted dict (the validated body drops
    # extra keys by design — schema sterility is never widened for transport).
    compiled = {}
    for s in submissions:
        if not s.get("stored"):
            continue
        dsl = raw_by_id.get(s.get("hypothesis_id", ""), {}).get("dsl")
        if isinstance(dsl, dict):
            try:
                compiled[s["fp"]] = DSL.compile_program(dsl).fingerprint
            except ValueError as e:
                compiled[s["fp"]] = f"REJECTED: {e}"

    ledger = {"estimated_cost": round(sum(p.research_cost for p in queued), 2),
              "n_queued": len(queued), "n_submitted": len(submissions),
              "n_rejected_schema": len(rejected_schema),
              "ts": cycle_ts}
    return {"ts": cycle_ts, "query": query, "dataset": dataset, "gateset": gateset,
            "n_briefs": len(briefs), "role_errors": [b.get("role_error") for b in briefs.values()
                                                     if b.get("role_error")],
            "submissions": submissions, "rejected_schema": rejected_schema,
            "plans": plans, "queue": [p.hypothesis_id for p in queued],
            "experiments": experiments, "manifests": manifests,
            "compiled": compiled, "ledger": ledger}


def _fp_of(hypothesis_id: str) -> str:
    from app.research_memory import store as ST
    for h in ST.list_hypotheses():
        if h["hypothesis_id"] == hypothesis_id:
            return h["fp"]
    return "unknown"


def _config_hash() -> str:
    from app.config import settings
    return hashlib.sha256(
        f"{settings.analyst_model()}|{settings.decider_model()}|"
        f"{settings.PROMPT_VERSION}|research".encode()).hexdigest()[:12]


def write_manifest(exp_id: str, proposal: ExperimentProposal, dataset: str,
                   gateset: str, manifest_dir: str = "data/experiments",
                   pit_membership_version: str = "", membership_hash: str = "",
                   event_batch_ids: list | None = None,
                   normalizer_version: str = "", taxonomy_version: str = "",
                   classifier_version: str = "", blackout_ruleset_version: str = "",
                   evidence_class: str = "ALPHA",
                   data_registry_version: str = "registry-v1",
                   snapshot_id: str = "",
                   artifact_hashes: list | None = None) -> str:
    """Immutable experiment manifest (§§27, 75). Hashes, never raw data.
    PIT/event/class fields default empty for pre-event experiments (additive)."""
    from app.governance.constitution import BURNED_DATASETS
    entry = BURNED_DATASETS.get(dataset, {})
    manifest = {
        "experiment_id": exp_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis_id": proposal.hypothesis_id,
        "code_commit": _code_commit(),
        "config_hash": _config_hash(),
        "dataset": dataset,
        "dataset_status": entry.get("status", "exploratory"),
        "dataset_hashes": {"dataset": FP.fp({"dataset": dataset})},
        "universe": "nifty500+pinned",
        "universe_hash": FP.fp({"universe": "nifty500+pinned"}),
        "pit_membership_version": pit_membership_version,
        "membership_hash": membership_hash,
        "event_batch_ids": event_batch_ids or [],
        "normalizer_version": normalizer_version,
        "taxonomy_version": taxonomy_version,
        "classifier_version": classifier_version,
        "blackout_ruleset_version": blackout_ruleset_version,
        "data_registry_version": data_registry_version,
        "snapshot_id": snapshot_id,
        "artifact_hashes": artifact_hashes or [],
        "evidence_class": evidence_class,
        "gate_version": gateset,
        "benchmark_version": "NIFTY50_TRI+v4-eqw",
        "cost_model_version": "env-v1+0.21pct-roundtrip",
        "research_agent_version": "roles-v1",
        "prompt_version": "m12",
        "parent_experiment": None,
    }
    os.makedirs(os.path.join(manifest_dir, exp_id), exist_ok=True)
    path = os.path.join(manifest_dir, exp_id, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    return path
