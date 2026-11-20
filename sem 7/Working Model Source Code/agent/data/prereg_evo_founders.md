# Prereg: Death-Engine MVP — 8 founders, genome ranges, selection protocol (NEWW_PLAN Day 2)

**Written:** before any `app/evo/` code or arena run. Deterministic, zero tokens.
**Scope lock:** forward paper ONLY. Backtest data never admits, kills, promotes,
or scores any variant. v4 stays burned; founders are starting points, not winners.

## 1. Genome (mutation ONLY inside these ranges — LLM never invents genes)

| Gene | Allowed values | Notes |
|---|---|---|
| `topK` | {30, 50, 70} | Selection breadth |
| `veto_strictness` | {0.5, 1.0, 2.0} | Multiplier on veto_fraction outputs, clipped to [0,1] |
| `vix_gate` | {on, off} | STRESSED-new-entry block + ELEVATED 0.5 cap |
| `gross_cap` | {0.5, 1.0} | Max gross exposure |
| `turnover_delta` | {0.010, 0.015, 0.020} | Dust threshold (fraction of book) |

v4-as-shipped == {50, 1.0, on, 1.0, 0.015}. Mutation = single-gene step to an
adjacent allowed value, max 2 children per generation, only from ALIVE parents
with trailing IR above the population median (no breeding from the dead or weak).

## 2. The 8 founders (diversity declared up front, never backtest-picked)

| # | Name | Genome |
|---|---|---|
| F1 | v4-as-shipped | {50, 1.0, on, 1.0, 0.015} |
| F2 | narrow-focus | {30, 1.0, on, 1.0, 0.015} |
| F3 | wide-net | {70, 1.0, on, 1.0, 0.015} |
| F4 | v3-narrow (no top-K era) | {50, 1.0, on, 1.0, 0.015} + veto off flag* |
| F5 | no-vix | {50, 1.0, off, 1.0, 0.015} |
| F6 | strict-veto | {50, 2.0, on, 1.0, 0.015} |
| F7 | loose-veto | {50, 0.5, on, 1.0, 0.015} |
| F8 | low-gross | {50, 1.0, on, 0.5, 0.020} |

\*F4 runs the v3 target pipeline (no rank cut) with veto disabled — the closest
thing to a control arm. Implemented as genome flags, not code forks.

## 3. Death judge (two-strike sequential rule + token starvation)

- A variant becomes *judgeable* only after **≥60 forward decisions** (rebalances).
  Before that: ALIVE, equal-weight allocation, no strikes possible (unlucky infancy
  is not evidence).
- Each judging window (60 decisions): compute trailing net IR
  (mean/std of daily net-of-costs excess vs NIFTY, annualized) and token spend.
- **Strike 1** if trailing IR < 0.0 (no edge, weak significance bar deliberately
  low — we kill demonstrated mediocrity, not bad luck) OR token spend exceeds
  its per-window budget with IR < 0.5 (starvation kills first).
  Effect: status → WEAKENED, allocation halved.
- **Strike 2** (consecutive window, same conditions): status → DEAD, allocation
  zero, tombstone written (cause stats + regime fingerprint). Strikes reset after
  one clean window (IR ≥ 0.0) — recovery is possible, forgiveness is logged.
- Dead variants are never deleted (seed bank). Living population capped at 8;
  children admitted only on a death vacancy (one in, one out — no inflation).

## 4. Seed bank + resurrection

Tombstone = {genome, birth/death dates, strikes log, regime fingerprint at death:
(vix_regime, index trend, breadth bucket)}. When the live fingerprint matches a
tombstone's death fingerprint on all three axes, the variant is resurrected ON
PROBATION (allocation capped at half normal, must survive one clean window or
re-die immediately). Rationale: the variant that dies in a bull market may own
the crash — death is cryopreservation, not deletion.

## 5. Allocation

Birth: equal weight across living. After ≥60 decisions: weight ∝ max(0, trailing
IR), renormalized; WEAKENED variants additionally halved. System P&L = weighted
population portfolio. Rebalance of allocation monthly (not per-rebalance — slow
money, fast judgment).

## 6. Lineage ledger (audit)

Every birth/death/weakening/resurrection/mutation logged with timestamp, genome
diff vs parent, judge statistics, and regime fingerprint. Tombstones + lineage
are the Monday demo artifact (family tree with causes of death).

## Gate

Day-2 exit is synthetic-ledger proof only: scripted return streams must produce
exactly the kill/resurrect/allocation transitions specified above. No forward
paper is judged until the Day-6 clock starts. Any threshold above may only change
via a new prereg amendment, never mid-arena.
