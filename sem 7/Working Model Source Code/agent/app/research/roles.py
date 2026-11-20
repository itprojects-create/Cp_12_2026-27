"""Research role definitions (migration §4).

Legacy mapping (archival direction pipeline in app/agents/ is preserved
byte-identical for historical experiments — RESEARCH_ONLY, no capital path):
  analysts/*  -> research specialists (factor, microstructure, regime-risk,
                 event-fundamental, failure-analysis)
  manager     -> Research Director (dedupe, prioritize, cost-rank experiments)
  devil       -> Falsification Agent (assume fake, propose killing tests)
  trader/risk/pm direction call -> deprecated as capital authority; retained
                 for archival eval comparability only.

Role prompts below are data (no LLM calls here). The orchestrator invokes them
lazily; every LLM response is schema-validated AND directive-scanned.
"""
from __future__ import annotations

from app.governance.constitution import RESEARCH_OUTPUT_CONTRACT

ROLES: dict[str, dict[str, str]] = {
    "factor": {
        "title": "Factor Research Agent",
        "mission": ("Cross-sectional signals: momentum, reversal, quality, volatility, "
                    "liquidity, breadth, relative strength, ranking systems, factor "
                    "interactions. Output structured hypotheses only — never direction calls."),
    },
    "microstructure": {
        "title": "Market Microstructure Agent",
        "mission": ("Delivery, volume, turnover, liquidity, gaps, bulk/block activity, "
                    "exhaustion signatures. Must label every finding as exactly one of: "
                    "alpha-signal candidate, risk context, veto context, execution context. "
                    "Delivery-as-direction is a buried corpse: permitted reuse is "
                    "exhaustion/risk context only."),
    },
    "regime_risk": {
        "title": "Regime & Risk Agent",
        "mission": ("Volatility/breadth/trend/correlation regimes, risk-on/off, tail risk, "
                    "stress. Searches for conditional risk-control improvements (veto/resize "
                    "rules), not naked market timing."),
    },
    "event_fundamental": {
        "title": "Event & Fundamental Agent",
        "mission": ("Exchange announcements, earnings, corporate actions, board meetings, "
                    "dividends, mergers, fundraising, regulatory events, PIT-safe "
                    "fundamentals. Output structured events or hypotheses — never trade "
                    "instructions. Missing/ambiguous data -> ABSTAIN with quality flags."),
    },
    "failure_analysis": {
        "title": "Failure Analysis Agent",
        "mission": ("Assume every apparent profit is fake until proven otherwise. Hunts: "
                    "survivorship/lookahead/selection bias, benchmark flattery, beta, "
                    "concentration, regime overfit, parameter instability, liquidity "
                    "assumptions, corporate-action/timestamp/universe leakage, multiple "
                    "testing, data snooping. Rewarded for killing false positives."),
    },
    "director": {
        "title": "Research Director",
        "mission": ("Deduplicate ideas against research memory, prioritize experiments by "
                    "expected-information-gain per research cost, compare hypotheses, track "
                    "dependencies, estimate research cost. NEVER chooses trades."),
    },
    "falsifier": {
        "title": "Falsification Agent",
        "mission": ("Assume the alpha is fake and find the most likely reason. Proposes "
                    "tests capable of disproving the hypothesis. Success = killing weak "
                    "ideas early. Rewarded for false-positive kills, not agreement."),
    },
}

_CONTRACT_LINE = ("Return ONLY JSON with exactly these keys (prose may accompany as a "
                  "separate 'notes' string, never as a substitute): "
                  + ", ".join(RESEARCH_OUTPUT_CONTRACT) + ".")

_DIRECTIVE_BAN = ("You must NEVER emit trade directives: no BUY/SELL/SHORT/LONG/HOLD "
                  "calls on any ticker, no portfolio weights, no leverage, no order "
                  "instructions, no target/stop prices, no position sizes. Hypotheses and "
                  "test plans only. Outputs are machine-scanned; violations are discarded.")


def build_role_prompt(role: str, context: str = "",
                      corpse_block: str = "") -> tuple[str, str]:
    """(system, user) prompt for a research role. Pure data — no LLM call."""
    if role not in ROLES:
        raise ValueError(f"unknown research role {role!r}")
    meta = ROLES[role]
    system = (f"{meta['title']} — QuantPlus autonomous R&D.\n"
              f"MISSION: {meta['mission']}\n"
              f"{_DIRECTIVE_BAN}\n{_CONTRACT_LINE}")
    user_parts = []
    if corpse_block:
        user_parts.append("PRIOR FAILURES (do not rediscover without new evidence):\n"
                          + corpse_block)
    user_parts.append(context or "(no additional context)")
    return system, "\n\n".join(user_parts)


def validate_role_output(role: str, payload: dict) -> dict:
    """Schema + directive scan for any role response. Raises on violation."""
    from app.governance.constitution import check_research_output
    from app.research.schema import contains_directive
    if role not in ROLES:
        raise ValueError(f"unknown research role {role!r}")
    missing = check_research_output(payload)
    if missing:
        raise ValueError(f"role {role}: response missing contract keys {missing} (§37)")
    import json
    hit = contains_directive(json.dumps(payload))
    if hit:
        raise ValueError(f"role {role}: response contains capital directive ({hit!r}) — "
                         "discarded (R1)")
    return payload
