# Preregistration: Veto Overlay + Sandboxed Manager Retry (one evaluation each)

**Written:** 2026-10-07, BEFORE either is evaluated on 2025H2-2026.
**Base:** core v3 (`core_backtest_v3.json`: Sharpe 0.705, MaxDD 12.46%).

## Overlay contract (money path, default)

The overlay may ONLY (a) VETO core entries it judges whipsaw/falling-knife risk,
(b) RESIZE within [0, core size]. It may never add direction, flip long->short,
or increase size. Deterministic veto fraction in [0,1]:
`final = core_size * (1 - veto)`.

Veto inputs (all PIT-clean, bars [:t+1] only):
- breadth: % NIFTY names with close>MA50 (from passed name_closes)
- VIX regime (trailing percentile, same as v3)
- exhaustion: name dist_from_20d_high + ret_5d (same math as features.py)
- event clustering: blackout set density in next 15 bars (if supplied)

Veto table (frozen):
- STRESSED + breadth<40% => veto 1.0 (full veto new entries)
- ELEVATED + breadth<40% => veto 0.5
- blowoff (dist_hi>-? actually dist_from_high <0.5% + ret5d>+8%) on LONG candidate => veto 1.0
- flush context + blackout-dense week => veto 0.5
- else 0.0

**Gate:** overlay beats core-v3 on Sharpe OR MaxDD over 2025-2026 unseen window,
same calendar, costs-in. If FAIL: LLM exits money path, stays explainability-only.

## Manager retry contract (sandbox, `manager_mode=retry`)

Same analysts, NEW manager synthesis prompt pack (m10):
- weight-of-evidence with explicit base-rate + falsifier checklist
- 5-tier rating output (Buy/Overweight/Hold/Underweight/Sell + REVIEW)
- direction from synthesis (full retry as requested), but SAME code guardrails
  (flat/BROKEN=>hold, M3 VIX, M4 counter-trend) still apply after reasoning.
- Separate sid namespace (`cfg|retry`), separate checkpoints, separate table.

**Gate (strict, one-shot):** retry must beat veto-overlay on Sharpe AND MaxDD
AND `beats_best_constant=True` on the unseen window. Else auto-revert to veto
for Monday ship. Recorded as-is either way.

## Windows

* Dev: 2021-2024 (may inspect). Test: 2025H2-2026 unseen (one read each).
* n: every core entry decision in window (not 24-scenario accuracy).
