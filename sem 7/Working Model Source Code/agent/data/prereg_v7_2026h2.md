# Prereg: v7-2026h2-unburned LLM-direction eval (written BEFORE the run)

**Date:** 2026-10-10 · **Prompt under test:** `PROMPT_VERSION=m12`, `DIRECTION_POLICY=llm`
**Purpose:** an honest, unburned read of the LLM pipeline AFTER the evidence-
grounding fix (data/prereg_manager_evidence.md). It is the read the m12 fix was
built for: does giving the deciders the real signals + code-computed tally move
direction quality, and does the pipeline add or subtract capital?

## Design (fixed before running)
- Set: `app/eval/scenarios_v7.py` — `SCENARIOS_V7`, 24 (ticker, as_of) pairs;
  same windows as v6 (2026-07-21..2026-08-25) but a different ticker per pair,
  zero pair overlap with v1/v5/v3rd/v4/v6. v6 was contaminated *by us* (its
  labels were printed to `eval_v6_run.log` during diagnosis), so v7 is the first
  set whose labels are unknown to us AND unseen by the model.
- Gates: `app/eval/gates.py`, frozen 2026-09-18, **unchanged** (MIN_DECISIVE=8,
  ACCURACY_MIN=0.55, NO_EDGE_HOLD_MIN=0.40, TRADE_RATE [0.20,0.90]).
- Horizon 20 trading days; decisive iff |fwd| >= 4%; labels computed at runtime.
- **New this run (report-only, gates unchanged):** alpha vs `^NSEI` per scenario
  and an `alpha` summary block. Rationale: single-name 20-day absolute return is
  dominated by market beta, so accuracy alone cannot separate skill from "matched
  the index" — alpha is the honest read and is the point of step 1.
- One-shot: run `scripts/run_eval_live.py --set v7` once. Infra-crash resume
  allowed (checkpoint-based, no re-billing), recorded as such. No prompt/gate/
  schema changes in response to the result.

## Verdict mapping (fixed before running)
- `n_decisive < 8` → INCONCLUSIVE (report as-is).
- Else PASS iff all frozen gate checks pass AND `beats_best_constant` is true.
- Anything else → FAIL, recorded as-is.

## Disclosures (added before the run)
- **Ticker swap:** `TATAMOTORS.NS` returned a Yahoo 404 ("quote not found" —
  delisted/renamed in this window) during a data-availability pre-flight and was
  replaced by `SBILIFE.NS` on the same date. A zero-token pre-flight over all 24
  pairs is run before the paid eval so a missing ticker cannot crash a run
  mid-way.
- **Pre-flight label visibility:** that availability check evaluates
  `forward_return` per pair, so the 24 v7 labels were visible on screen before
  the run. Disclosed for honesty; the discipline it protects is unchanged and is
  the binding constraint: **no prompt, gate, schema, or scenario change is made
  in response to the result or to those labels.** No tuning occurred and none will.

## Explicit non-goals
No tuning, no prompt edits, no gate moves. This measures the current pipeline's
accuracy, its alpha, and whether it adds or subtracts capital.
