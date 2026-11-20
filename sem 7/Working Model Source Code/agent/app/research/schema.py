"""Research hypothesis schema (migration §5).

Typed, falsifiable, capital-sterile: the schema REJECTS direct BUY/SELL
recommendations, ticker-specific direction commands, portfolio weights,
leverage instructions, and order instructions at parse time. An LLM may fill
every field — none of them can command capital.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

StrategyFamily = Literal[
    "ranking", "veto_filter", "risk_filter", "regime_filter", "exit_rule",
    "entry_rule", "universe_filter", "portfolio_weighting", "execution_filter",
    "event_filter", "ensemble_rule",
]

EvidenceClass = Literal["ALPHA", "RISK_CONTROL", "EXECUTION", "UNIVERSE", "DATA_QUALITY"]

# Capital-directive patterns rejected in every free-text field. Narrow by
# design: research prose about mechanisms ("momentum", "pressure", "bias as a
# statistical term") must pass; only explicit trade/position directives fail.
_FORBIDDEN = (
    re.compile(r"\b(buy|sell|short|cover)\s+[A-Z][A-Z0-9.\-]*\.NS\b", re.IGNORECASE),
    re.compile(r"\b(place|executing?|route|send)\s+(a|an|the)?\s*(market|limit|stop)?\s*orders?\b",
               re.IGNORECASE),
    re.compile(r"\b(portfolio\s+)?weights?\s*[:=]\s*[\d\[]", re.IGNORECASE),
    re.compile(r"\bleverage\s*(of\s*)?\d", re.IGNORECASE),
    re.compile(r"\b\d\s*x\s*leverage\b", re.IGNORECASE),
    re.compile(r"\b(target\s+price|take-?profit|stop-?loss)\s*(of|at|is|=)?\s*(rs\.?|₹|\d)",
               re.IGNORECASE),
    re.compile(r"\bnotional\s*[:=]", re.IGNORECASE),
)


def _sterile(text: str, field: str) -> str:
    for pat in _FORBIDDEN:
        m = pat.search(text or "")
        if m:
            raise ValueError(
                f"{field} contains a capital directive ({m.group(0)!r}) — hypotheses "
                "may not command trades, weights, leverage, or orders (R1)")
    return text


def contains_directive(text: str) -> str | None:
    """Return the first capital-directive match in free text, else None.

    Shared by role prompts and output validation: LLMs are instructed against
    these patterns AND their outputs are scanned for them (defense in depth).
    """
    for pat in _FORBIDDEN:
        m = pat.search(text or "")
        if m:
            return m.group(0)
    return None


class ParameterRange(BaseModel):
    model_config = {"frozen": True}
    lo: float
    hi: float
    grid: tuple[float, ...] = ()

    def validate_range(self) -> "ParameterRange":
        if not self.lo <= self.hi:
            raise ValueError("ParameterRange lo must be <= hi")
        if self.grid and any(not (self.lo <= g <= self.hi) for g in self.grid):
            raise ValueError("ParameterRange grid must sit inside [lo, hi]")
        return self


class ResearchHypothesis(BaseModel):
    model_config = {"frozen": True}
    hypothesis_id: str = Field(min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str = Field(min_length=8, max_length=200)
    thesis: str = Field(min_length=40, max_length=4000)
    economic_reason: str = Field(min_length=20, max_length=2000)
    strategy_family: StrategyFamily
    evidence_class: EvidenceClass = "ALPHA"  # P4 §31: declared per hypothesis
    required_features: list[str] = Field(min_length=1)
    parameter_ranges: dict[str, ParameterRange] = Field(default_factory=dict)
    expected_regimes: list[str] = Field(default_factory=list)
    claimed_mechanism: str = Field(min_length=10, max_length=1000)
    falsification_tests: list[str] = Field(min_length=1)
    expected_failure_modes: list[str] = Field(default_factory=list)
    prohibited_data: list[str] = Field(default_factory=list)
    estimated_research_cost: float = Field(ge=0.0)
    parent_hypotheses: list[str] = Field(default_factory=list)
    novelty_claim: str = Field(min_length=10, max_length=1000)
    # P6 calibration priors (research metadata ONLY — never read by any
    # capital-path module; isolation enforced by test). Optional so existing
    # stored hypotheses validate unchanged.
    estimated_probability_survives_backtest: float | None = Field(default=None, ge=0.0, le=1.0)
    estimated_probability_survives_falsification: float | None = Field(
        default=None, ge=0.0, le=1.0)
    estimated_probability_reaches_shadow: float | None = Field(
        default=None, ge=0.0, le=1.0)
    estimated_probability_reaches_promotion: float | None = Field(
        default=None, ge=0.0, le=1.0)

    @field_validator("thesis", "economic_reason", "claimed_mechanism",
                     "novelty_claim", "title")
    @classmethod
    def _no_directives(cls, v: str, info) -> str:
        return _sterile(v, info.field_name)

    @field_validator("falsification_tests", "expected_failure_modes")
    @classmethod
    def _no_directives_list(cls, v: list[str], info) -> list[str]:
        return [_sterile(t, info.field_name) for t in v]


class FalsificationPlan(BaseModel):
    """What the Falsification Agent will run to try to kill the hypothesis."""
    model_config = {"frozen": True}
    hypothesis_id: str
    tests: list[str] = Field(min_length=1)  # e.g. beta-match, leave-one-out, placebo
    kill_criteria: list[str] = Field(min_length=1)
    max_research_cost: float = Field(ge=0.0)


class ExperimentProposal(BaseModel):
    """Research-Director output: which experiment to run, at what cost, why."""
    model_config = {"frozen": True}
    hypothesis_id: str
    falsification_plan: FalsificationPlan
    dataset: str  # must exist in constitution registry; promotion needs FORWARD_ONLY
    gateset: str = "GATESET_FROZEN_20260918"
    expected_information_gain: float = Field(ge=0.0)
    research_cost: float = Field(ge=0.0)
    rationale: str = Field(min_length=10, max_length=1000)

    @property
    def priority(self) -> float:
        """R&D ranking metric (§26): information per unit research cost."""
        return self.expected_information_gain / max(self.research_cost, 1e-9)

    @field_validator("rationale")
    @classmethod
    def _no_directives(cls, v: str, info) -> str:
        return _sterile(v, info.field_name)
