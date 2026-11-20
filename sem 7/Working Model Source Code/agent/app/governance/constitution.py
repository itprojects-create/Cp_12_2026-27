"""QuantPlus constitution: machine-readable governance (migration §1).

15 rules. LLM output is research input only — capital decisions come from
deterministic, version-controlled code. This module is import-safe (stdlib +
pydantic only) so boundary tests and the money path can depend on it without
pulling any LLM or broker code.
"""
from __future__ import annotations

from enum import Enum

CONSTITUTION_VERSION = "v1"


class StrategyStatus(str, Enum):
    """Every claim about a strategy must use one of these labels (§15/§56).

    BACKTEST_POSITIVE is not PROVEN_ALPHA; SURVIVED_UNSEEN_PERIOD is not
    DEPLOYMENT_READY. Promotion claims require FORWARD evidence (§15).
    """
    EXPERIMENTAL = "EXPERIMENTAL"
    BACKTEST_ONLY = "BACKTEST_ONLY"
    BACKTEST_POSITIVE = "BACKTEST_POSITIVE"
    HISTORICALLY_SURVIVED = "HISTORICALLY_SURVIVED"
    SHADOW = "SHADOW"
    FORWARD_VALIDATING = "FORWARD_VALIDATING"
    CHAMPION = "CHAMPION"
    RETIRED = "RETIRED"
    DEAD = "DEAD"
    # Failure terminals (research-memory §8 + death-engine §16)
    PROPOSED = "PROPOSED"
    DUPLICATE = "DUPLICATE"
    REJECTED_SCHEMA = "REJECTED_SCHEMA"
    EXPERIMENTING = "EXPERIMENTING"
    FAILED_BACKTEST = "FAILED_BACKTEST"
    FAILED_FALSIFICATION = "FAILED_FALSIFICATION"
    FAILED_DSR = "FAILED_DSR"
    FAILED_PBO = "FAILED_PBO"
    FAILED_COST = "FAILED_COST"
    FAILED_CONCENTRATION = "FAILED_CONCENTRATION"
    FAILED_FORWARD = "FAILED_FORWARD"


# Statuses that may never be described with promotion language (§15/§56).
NON_PROMOTION_STATUSES = frozenset({
    StrategyStatus.EXPERIMENTAL, StrategyStatus.BACKTEST_ONLY,
    StrategyStatus.BACKTEST_POSITIVE, StrategyStatus.HISTORICALLY_SURVIVED,
    StrategyStatus.SHADOW, StrategyStatus.FORWARD_VALIDATING,
})

PROMOTION_CLAIM_PHRASES = (
    "profitable", "production ready", "production-ready", "validated",
    "alpha generating", "alpha-generating", "proven alpha", "deployment ready",
    "deployment-ready",
)


class DatasetStatus(str, Enum):
    EXPLORATORY = "exploratory"
    VALIDATION = "validation"
    BURNED = "burned"
    FORWARD_ONLY = "forward-only"
    RETIRED = "retired"


# Registry of research datasets/periods (§7). Burned sets may be used for
# regression/falsification/architecture validation — never for promotion.
BURNED_DATASETS: dict[str, dict[str, str]] = {
    "v1-2023-2024": {"period": "2023-07..2024-12", "status": DatasetStatus.BURNED,
                     "note": "direction-finding reuse x3+"},
    "v5-2025-disjoint": {"period": "2025-01..2025-12", "status": DatasetStatus.BURNED,
                         "note": "direction-finding reuse x3+"},
    "v3rd-2026-clean": {"period": "2026-01..2026-07", "status": DatasetStatus.BURNED,
                        "note": "m3 + retry-m10 reads"},
    "v4-2022-blind": {"period": "2022", "status": DatasetStatus.BURNED,
                      "note": "H1 trend-direction read (FAIL 0.111)"},
    "v6-2026h2-unburned": {"period": "2026-07-21..2026-08-25", "status": DatasetStatus.VALIDATION,
                           "note": "partial 14/24; labels exposed in run log -> treat as exploratory"},
    "v7-2026h2-unburned": {"period": "2026-07-21..2026-08-25", "status": DatasetStatus.VALIDATION,
                           "note": "partial 10/24; pre-flight label visibility disclosed"},
    "backtest-2021-2026": {"period": "2021-01-01..2026-10-01", "status": DatasetStatus.BURNED,
                           "note": "12 DSR trials; promotion-burned, falsification-only"},
    "blind-2015-2020": {"period": "2015-01-01..2020-12-31", "status": DatasetStatus.BURNED,
                        "note": "single survival read; burned by that read"},
    "forward-from-2026-10-10": {"period": "2026-10-10..", "status": DatasetStatus.FORWARD_ONLY,
                                "note": "only promotion-grade evidence source"},
}


class Gateset(str, Enum):
    """Versioned promotion-gate sets (§18). Thresholds are frozen per version;
    a new philosophy means a new version + prereg, never a silent edit."""
    FROZEN_20260918 = "GATESET_FROZEN_20260918"


GATESETS: dict[str, dict[str, float | int]] = {
    Gateset.FROZEN_20260918: {
        "min_decisive": 8, "accuracy_min": 0.55, "no_edge_hold_min": 0.40,
        "trade_rate_lo": 0.20, "trade_rate_hi": 0.90,
    },
}

RULES: tuple[dict[str, str], ...] = (
    {"id": "R1", "title": "No LLM capital authority",
     "statement": "LLM output may generate research hypotheses; it must never directly "
                  "determine direction, weight, quantity, exposure, leverage, stops, "
                  "targets, entries, exits, or allocation.",
     "enforced_by": "schemas.FinalDecision.authority=RESEARCH_ONLY + boundary tests"},
    {"id": "R2", "title": "No LLM upsizing",
     "statement": "No LLM component may increase exposure beyond the deterministic engine; "
                  "temporary veto/resize use must be experimental, tagged, and measured "
                  "against a no-LLM control.",
     "enforced_by": "core.overlay.llm_overlay_size + LLM_OVERLAY_ENABLED=false default"},
    {"id": "R3", "title": "Opinion is not alpha",
     "statement": "Confidence, consensus, votes, or Devil approval are never profitability "
                  "evidence. Only measured out-of-sample evidence counts.",
     "enforced_by": "promotion gates (R10 metrics); confidence is research metadata"},
    {"id": "R4", "title": "Hypotheses become deterministic code",
     "statement": "Hypothesis -> proposal -> validation -> implementation -> backtest -> "
                  "statistics -> shadow -> forward -> promotion. No shortcut.",
     "enforced_by": "research schema + DSL + foundry + orchestrator"},
    {"id": "R5", "title": "Code cannot promote itself",
     "statement": "Candidates generate metrics; a separate deterministic judge promotes.",
     "enforced_by": "evo judge + champion promotion logic"},
    {"id": "R6", "title": "History kills faster than it promotes",
     "statement": "Backtests reject aggressively; historical results alone never grant "
                  "production authority; repeated optimization = contamination.",
     "enforced_by": "dataset registry statuses; forward requirement"},
    {"id": "R7", "title": "Burned datasets stay burned",
     "statement": "Exploratory/validation/burned/forward-only status is tracked per dataset.",
     "enforced_by": "BURNED_DATASETS registry"},
    {"id": "R8", "title": "Forward evidence rules",
     "statement": "Post-historical survivors enter shadow/forward before champion status.",
     "enforced_by": "forward clock + FORWARD_REQUIRED_FOR_PROMOTION"},
    {"id": "R9", "title": "Compete against baselines",
     "statement": "Cash, benchmark, champion, simpler strategy, beta/exposure-matched control.",
     "enforced_by": "eval.incremental_alpha"},
    {"id": "R10", "title": "CAGR is never enough",
     "statement": "Sharpe/Sortino/DD/CVaR/turnover/costs/concentration/beta/PBO/DSR/forward required.",
     "enforced_by": "promotion gateset evaluation"},
    {"id": "R11", "title": "Net of reality",
     "statement": "Brokerage, taxes, costs, slippage, circuits, liquidity, cash drag, "
                  "inference + data costs included where applicable.",
     "enforced_by": "environment costs + friction matrix + research economics"},
    {"id": "R12", "title": "Research compute justifies itself",
     "statement": "Inference is an explicit research cost tracked per hypothesis lineage.",
     "enforced_by": "research economics ledger; strategy vs research economics split"},
    {"id": "R13", "title": "Dead ideas stay dead",
     "statement": "Failures get fingerprints; rediscovery without new evidence is rejected.",
     "enforced_by": "research memory corpse registry + dedup"},
    {"id": "R14", "title": "Reproducibility",
     "statement": "Version + fingerprints + config + universe + timestamp reproduce any decision.",
     "enforced_by": "experiment manifests + reproduce_experiment.py"},
    {"id": "R15", "title": "No deployment claim without evidence",
     "statement": "Status labels only (§15); promotion language requires forward evidence.",
     "enforced_by": "describe() guard"},
)

# §37 — every LLM research response must carry this structure (prose may accompany,
# never substitute).
RESEARCH_OUTPUT_CONTRACT: tuple[str, ...] = (
    "hypotheses", "rejected_prior_ideas", "recommended_experiments",
    "required_data", "falsification_plan", "uncertainties", "estimated_value",
)


def check_research_output(payload: dict) -> list[str]:
    """Return missing contract keys (empty = compliant). Never raises."""
    if not isinstance(payload, dict):
        return list(RESEARCH_OUTPUT_CONTRACT)
    return [k for k in RESEARCH_OUTPUT_CONTRACT if k not in payload]


def describe(status: StrategyStatus | str, text: str) -> str:
    """Guard promotion language (§15/§56). Raises ValueError when `text`
    describes a non-promotion status with promotion phrases."""
    s = StrategyStatus(status)
    if s in NON_PROMOTION_STATUSES:
        low = text.lower()
        for phrase in PROMOTION_CLAIM_PHRASES:
            if phrase in low:
                raise ValueError(
                    f"status {s.value} must not be described as '{phrase}' (R15)")
    return text


def dataset_status(name: str) -> DatasetStatus:
    """Registry lookup (§7). Unknown datasets are EXPLORATORY (never assumed clean)."""
    entry = BURNED_DATASETS.get(name)
    if entry is None:
        return DatasetStatus.EXPLORATORY
    return DatasetStatus(entry["status"])


def promotion_eligible_dataset(name: str) -> bool:
    """Only forward-only evidence promotes (R6/R7/R8)."""
    return dataset_status(name) == DatasetStatus.FORWARD_ONLY


def assert_research_only(decision: object) -> object:
    """Type-level boundary (§3): session-pipeline outputs must literally carry
    authority=RESEARCH_ONLY plus the three invariant flags. Missing or False
    fails closed — absence is never treated as compliance."""
    auth = getattr(decision, "authority", "MISSING")
    if auth != "RESEARCH_ONLY":
        raise ValueError(
            f"capital boundary: expected RESEARCH_ONLY output, got authority={auth!r} (R1)")
    for flag in ("cannot_create_position", "cannot_reverse_position",
                 "cannot_increase_exposure"):
        if getattr(decision, flag, "MISSING") is not True:
            raise ValueError(f"capital boundary: {flag} not asserted True (R1/R2)")
    return decision
