"""Falsification Agent: assume fake, propose killing tests (§4G).

Deterministic core: per-family default test plans + the canonical test menu.
The opt-in LLM pass (`falsify`) may extend the plan — it cannot remove
required tests and its output is contract + directive validated.
"""
from __future__ import annotations

TEST_MENU: tuple[str, ...] = (
    "beta-match", "exposure-match", "leave-one-stock-out", "leave-top-out",
    "leave-one-sector-out", "leave-one-year-out", "leave-one-regime-out",
    "delayed-entry", "increased-cost", "universe-perturbation",
    "alternate-benchmark", "parameter-neighborhood", "walk-forward",
    "pre-post-regime-split", "shuffled-labels", "placebo-feature",
    "random-ranking-control", "random-timing-control",
)

# Required tests per strategy family: the falsifier cannot waive these.
REQUIRED_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "ranking": ("beta-match", "leave-top-out", "parameter-neighborhood", "placebo-feature"),
    "veto_filter": ("leave-one-regime-out", "placebo-feature", "increased-cost"),
    "risk_filter": ("leave-one-regime-out", "pre-post-regime-split", "alternate-benchmark"),
    "regime_filter": ("leave-one-regime-out", "pre-post-regime-split", "walk-forward"),
    "exit_rule": ("delayed-entry", "increased-cost", "parameter-neighborhood"),
    "entry_rule": ("delayed-entry", "random-timing-control", "increased-cost"),
    "universe_filter": ("universe-perturbation", "alternate-benchmark", "leave-one-sector-out"),
    "portfolio_weighting": ("exposure-match", "beta-match", "leave-top-out"),
    "execution_filter": ("increased-cost", "delayed-entry", "random-timing-control"),
    "event_filter": ("pre-post-regime-split", "leave-one-year-out", "placebo-feature"),
    "ensemble_rule": ("beta-match", "exposure-match", "leave-one-stock-out"),
}


def plan_for(strategy_family: str, extra: list[str] | None = None) -> dict:
    """Deterministic falsification plan: required tests + valid extras."""
    if strategy_family not in REQUIRED_BY_FAMILY:
        raise ValueError(f"unknown strategy family {strategy_family!r}")
    tests = list(REQUIRED_BY_FAMILY[strategy_family])
    for t in extra or []:
        if t not in TEST_MENU:
            raise ValueError(f"unknown falsification test {t!r}")
        if t not in tests:
            tests.append(t)
    return {"strategy_family": strategy_family, "required": list(tests),
            "kill_criteria": ["any required test reverses the claimed edge",
                              "edge concentrated in one name/year/regime (see LOO)",
                              "edge vanishes under +50% costs or 1-rebalance delay"]}


def build_falsifier_prompt(hypothesis: dict, corpse_block: str = "") -> tuple[str, str]:
    from app.research.roles import build_role_prompt
    import json
    plan = plan_for(hypothesis.get("strategy_family", "veto_filter"))
    ctx = ("Hypothesis under test:\n"
           + json.dumps(hypothesis, indent=1, default=str)[:4000]
           + "\n\nMandatory test plan (you may ADD tests, never remove):\n"
           + json.dumps(plan, indent=1))
    return build_role_prompt("falsifier", ctx, corpse_block)


def check_plan_covers(plan: dict, strategy_family: str) -> list[str]:
    """Tests required for the family that the plan omits (empty = covered)."""
    required = set(REQUIRED_BY_FAMILY[strategy_family])
    return sorted(required - set(plan.get("required", []) + plan.get("tests", [])))
