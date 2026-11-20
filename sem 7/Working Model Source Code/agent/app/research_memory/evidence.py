"""Evidence records: complete, auditable experiment metadata (§§8, 27, 53).

An experiment record must answer: who/what proposed it, what hypothesis,
what code, which data (PIT-safe?), which benchmark, which cost model, which
tests survived, which failed, lineage, promotion state, forward evidence.
Missing answers are recorded as missing — never imputed.
"""
from __future__ import annotations

REQUIRED_FIELDS = (
    "hypothesis_id", "hypothesis_fp", "creator_agent", "strategy_fp",
    "parameter_fp", "data_fp", "data_status", "universe", "features",
    "code_version", "gateset", "benchmark", "cost_model",
)

OPTIONAL_FIELDS = (
    "parent_fp", "backtests", "metrics", "falsification_tests", "pbo",
    "dsr", "beta", "factor_exposures", "cost_sensitivity", "regime_results",
    "failure_reason", "forward_results", "status", "research_cost",
)


def build_evidence_record(**kw) -> dict:
    """Assemble a record; missing REQUIRED fields raise (fail-closed)."""
    missing = [f for f in REQUIRED_FIELDS if f not in kw or kw[f] in (None, "")]
    if missing:
        raise ValueError(f"evidence record missing required fields: {missing} (R14)")
    rec = {k: kw.get(k) for k in REQUIRED_FIELDS + OPTIONAL_FIELDS if k in kw}
    rec.setdefault("status", "EXPERIMENTING")
    return rec


def manifest(experiment_id: str, record: dict) -> dict:
    """Immutable experiment manifest (§27). Hashes, not data — reproducible
    lookup without ambiguity."""
    return {
        "experiment_id": experiment_id,
        "hypothesis_id": record.get("hypothesis_id"),
        "strategy_fingerprint": record.get("strategy_fp"),
        "parameter_fingerprint": record.get("parameter_fp"),
        "data_fingerprint": record.get("data_fp"),
        "data_status": record.get("data_status"),
        "universe": record.get("universe"),
        "gate_version": record.get("gateset"),
        "benchmark_version": record.get("benchmark"),
        "cost_model_version": record.get("cost_model"),
        "code_version": record.get("code_version"),
        "parent_experiment": record.get("parent_fp"),
    }
