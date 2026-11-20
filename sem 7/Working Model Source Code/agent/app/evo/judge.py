"""Death judge: two-strike sequential rule + token starvation (prereg §3).

Judgeable only after MIN_DECISIONS forward decisions. Weak significance bar is
deliberate: we kill demonstrated mediocrity, not bad luck. Pure math — no LLM.
"""
from __future__ import annotations

import math

MIN_DECISIONS = 60  # prereg §3: infancy is not evidence

# Per-window token budget is set by the arena caller (depends on founder vs
# child cost profile); the judge only enforces the number it is given.


def trailing_ir(daily_excess: list[float]) -> float:
    """Annualized information ratio of daily net-of-costs excess vs NIFTY."""
    if len(daily_excess) < 2:
        return 0.0
    mu = sum(daily_excess) / len(daily_excess)
    var = sum((r - mu) ** 2 for r in daily_excess) / (len(daily_excess) - 1)
    if var <= 1e-20:
        # constant (or float-dust) series: no measurable edge, never inf
        return 0.0
    return (mu / math.sqrt(var)) * math.sqrt(252.0)


def judge_window(n_decisions: int, ir: float, tokens_spent: int, token_budget: int) -> dict:
    """One judging window -> {verdict: clean|strike, reasons[], ir}."""
    reasons: list[str] = []
    if n_decisions < MIN_DECISIONS:
        return {"verdict": "clean", "reasons": ["infancy: not judgeable"], "ir": ir}
    if ir < 0.0:
        reasons.append(f"trailing IR {ir:.3f} < 0.0 (no edge)")
    if tokens_spent > token_budget and ir < 0.5:
        reasons.append(f"starvation: {tokens_spent} tokens > budget {token_budget} with IR {ir:.3f} < 0.5")
    return {"verdict": "strike" if reasons else "clean", "reasons": reasons, "ir": ir}
