"""W2 headless Automated Quant Research Lab (blueprint §7).

A separate research plane (per the W1 precedent): the runtime app and its
research/foundry modules are NOT imported. Reuses, unchanged:

- the exact W0 paper-book fee model (``research_v3.economics``),
- W1 PIT warehouse primitives (``research_v3.warehouse``: available_at joins,
  as-of membership spells with strict/weak disclosure, verified-action factors,
  official TRI benchmark),
- W1 boundary-exit semantics (execution rolls open-to-open, no skipped
  overnight move),
- the V2 foundry's capital-sterile/fingerprint philosophy (specs are DATA with
  allowlisted fields; trade directives fail at parse time).

Exports:
    run_backtest(StrategySpec)      -> BacktestResult
    run_sweep(StrategySpec, grid)   -> SweepResult   (bounded, holdout-free)
    run_cost_scenarios(spec)        -> base/double-cost net summaries
    challenge_finding(result)       -> ChallengeReport
    ResearchJournal                 -> append-only holdout/prereg registry
    research_journal_status(...)    -> VersionedState
"""
from .spec import (
    BacktestResult, ChallengeReport, ExecutionSpec, SignalSpec, SpecError,
    StrategySpec, SweepResult, UniverseSpec, WindowSpec, fingerprint)
from .data import PitPanel, list_data_coverage
from .runner import (
    MAX_GRID_CARDINALITY, compare_runs, run_backtest, run_cost_scenarios,
    run_sweep)
from .challenge import challenge_finding
from .journal import (
    JournalError, ResearchJournal, research_journal_status, require_sealed)

__all__ = [
    "BacktestResult", "ChallengeReport", "ExecutionSpec", "SignalSpec",
    "SpecError", "StrategySpec", "SweepResult", "UniverseSpec", "WindowSpec",
    "PitPanel", "list_data_coverage", "MAX_GRID_CARDINALITY", "run_backtest",
    "run_cost_scenarios", "run_sweep", "compare_runs", "challenge_finding",
    "ResearchJournal", "JournalError", "research_journal_status",
    "require_sealed", "fingerprint",
]
