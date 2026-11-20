# Pre-registration amendment #1 — trend core exposure normalization (v2)

**Written:** 2026-10-06, AFTER the v1 backtest (`data/core_backtest_20261006.json`),
BEFORE the v2 re-run. One amendment, one re-run, recorded as-is.

## v1 result (recorded as-is, not superseded)

Window 2021-01..2026-09 (1420 bars, 36 names, costs applied): CAGR 17.7%,
Sharpe 0.80, MaxDD 37.4%, avg gross exposure **1.358**, 1232 switches,
total cost 13.0% of book. Equal-weight B&H same universe: CAGR 30.3%,
Sharpe 1.25, MaxDD 17.2%.

## Why this amendment exists (a construction bug, not tuning)

`run_core()` sizes each qualifying name at `min(0.10, TARGET_VOL/vol)` with no
portfolio-level constraint, so the book's gross exposure averaged **135.8%**
(peaking ~360% when all 36 names qualified). The module docstring always said
positions are "fractions of book" (Σ ≤ 100%); the code contradicted it. The
v1 drawdowns (-43.8% intra-2021) and B&H underperformance are dominated by this
unintended leverage, not by the trend signal itself. Fixing the code to match
its own written rule is a correction, not a re-tune.

## The one change (v2)

Add a single portfolio constraint at each rebalance, applied deterministically
after the frozen per-name rule:

- `GROSS_CAP = 1.00` (Σ of position fractions ≤ 100% of book, cash earns 0).
- If Σ targets > 1.00, scale all qualifying positions by `1.00 / Σ` (proportional,
  no name selection, no per-name re-sizing logic — the frozen per-name rule and
  its ordering are untouched).

Nothing else changes: trend rule, 60d momentum filter, vol targeting, 10% cap,
weekly rebalance, cost model, universe, window — all identical to the frozen rule.

## Honest expectation (stated before the run)

Exposure drops ~135.8% → ≤100% average, so absolute CAGR will FALL from 17.7%.
The question v2 answers is whether the signal is positive **at honest, unlevered
scale** and what its real risk profile is. B&H may still win on this bull-heavy,
survivorship-biased tape — that outcome would be recorded as-is and would
motivate the LLM overlay's actual mandate: add value vs the core where the core
bleeds (whipsaw regimes, falling-knife names), not beat B&H outright.

## Success criteria for the core (unchanged from the plan, applied to v2)

- CAGR > 0 after costs (a tradeable strategy exists), AND
- MaxDD materially below what the same capital in B&H experienced is NOT required
  (B&H comparison is disclosed context, not a gate for the core itself).
- The overlay (next phase) must beat core-v2 on Sharpe or MaxDD or it gets cut.
