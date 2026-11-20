# Prereg: v6-2026h2-unburned LLM direction eval (written BEFORE the run)

**Date:** 2026-10-10 · **Prompt under test:** `PROMPT_VERSION=m11`, `DIRECTION_POLICY=llm`
**Purpose:** get today's honest directional-accuracy read for the LLM pipeline on a
window that has never been evaluated (all prior sets — v1/v5/v3rd/v4 — are burned).

## Design (fixed before running)
- Set: `app/eval/scenarios_v6.py` — `SCENARIOS_V6`, 24 (ticker, as_of) pairs, each
  ticker once, window 2026-07-21..2026-08-25, zero pair overlap with v1/v5/v3rd/v4.
- Gates: `app/eval/gates.py`, frozen 2026-09-18, **unchanged** (MIN_DECISIVE=8,
  ACCURACY_MIN=0.55, NO_EDGE_HOLD_MIN=0.40, TRADE_RATE [0.20, 0.90]).
- Horizon 20 trading days; decisive iff |fwd| >= 4%; labels computed at runtime only.
- One-shot: run `scripts/run_eval_live.py --set v6` once. Infra-crash resume allowed
  (checkpoint-based, no re-billing), recorded as such. No prompt/gate/schema changes
  are made in response to the result.

## Verdict mapping (fixed before running)
- `n_decisive < 8` → INCONCLUSIVE (report as-is).
- Else PASS iff all gate checks pass AND `beats_best_constant` is true (the honest
  anchor: a PASS that does not beat the best constant rule is drift, not skill).
- Anything else → FAIL, recorded as-is.

## Explicit non-goals
No tuning, no prompt edits, no gate moves. This is measurement for the question
"what is the LLM's current accuracy, and does it add or subtract capital?".
