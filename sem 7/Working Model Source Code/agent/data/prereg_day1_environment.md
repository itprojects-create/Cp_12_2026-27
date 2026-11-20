# Prereg Amendment — Day 1: Honest Environment (NEWW_PLAN)

**Written:** before any Day-1 implementation or re-run. All changes deterministic, zero tokens.
**Rule frozen:** v4 (`app/core/trend_core_v4.py`) untouched — this amendment changes only the
*measurement environment* (costs, fills, calendar, ledger), never selection logic.

## 1. Segment-aware costs (replaces flat 0.21% round-trip)

| Segment | Per-side cost | Rationale |
|---|---|---|
| NIFTY50 / large-cap delivery | 0.105% | Unchanged (STT 0.10% + brokerage/slippage) |
| NIFTY500 non-50 | 0.20% | Wider spreads, lower depth |
| SME | 1.50% | 1–3% observed spreads; honest by construction |

`COST_PER_SIDE` becomes `cost_per_side(tier)`; tier from `app/data/universe.py`.
Fractional backtests keep flat 0.105% for comparability and report both.

## 2. Circuit non-fill modeling

NSE price bands 2/5/10/20%: if `|close/open − 1| >= band − 0.1%` AND day range
< 0.5% (locked), orders in that name do not fill — position carries at limit
price, no cost booked, fill deferred to next tradable bar. Band per name from
rolling 20d realized range (proxy; exact band feed deferred to NSE archives).
Conservative direction: assumes we are always on the wrong side of the lock.

## 3. Known-event calendar (deterministic, no prediction)

Hardcoded 2026–27: RBI MPC dates (6/yr, pre-announced), Union Budget (Feb 1),
election dates when Gazette-notified. Rule: halve gross (`×0.5`) over
[t−2, t+1] trading days around each event. Volatility is forecastable even
when direction isn't — this is risk shape, not alpha.

## 4. Token-spend deduction in paper ledger

Every paper report deducts cumulative inference spend (tokens × blended
₹/1K from gateway ledger) from P&L. A strategy must clear its own cognition
cost. Applies to paper ledger from Day 1 forward; historical reports keep
gross numbers with this note attached.

## Gate

Day-1 re-runs are diagnostic only (no PASS/FAIL shopping): backtest numbers
are *expected to drop*. If any number rises, the change is re-audited before
merge — improvements to measurement must not smuggle in edge.
