"""Versioned, read-only strategy-hypothesis library (Wave 5)."""

from .catalog import initial_strategy_revisions
from .contracts import (
    Citation,
    EligibilityReport,
    StrategyRequirement,
    StrategyRevision,
    StrategyTemplate,
    StudyAttachment,
    assess_eligibility,
    compile_strategy_spec,
)
from .registry import StrategyLibrary

__all__ = [
    "Citation",
    "EligibilityReport",
    "StrategyRequirement",
    "StrategyRevision",
    "StrategyTemplate",
    "StudyAttachment",
    "StrategyLibrary",
    "assess_eligibility",
    "compile_strategy_spec",
    "initial_strategy_revisions",
]
