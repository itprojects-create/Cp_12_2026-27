# v5.1 Interim Report — implementation + probe DONE, evals PENDING billing

**Date:** 2026-09-19 · **Prompts:** v5.1 · **Gates:** frozen 2026-09-18, unchanged ·
**M3, M4, Trader, Risk, PM untouched** (verified: no diff in those modules this iteration
except the Devil input plumbing specified in Part A).

## What was built

**Part A — raw exhaustion cross-wire.** New frozen `RawExhaustionSignals` model
(flush/blowoff/ret_5d/dist_lo/dist_hi, all required). Technical computes the dict
once, renders its prompt line from it, and checkpoints it; `build_devil_prompt`
takes it as a separate `raw_exhaustion_signals` payload field, and
`run_devils_advocate` accepts it as an optional param the graph fills from the
checkpoint. Pre-v5.1 sessions render "unavailable" (never treated as evidence).
No recompute anywhere on the Devil path.

**Part B — prompt patch only.** Added RAW SIGNAL OVERRIDE + 3 WORKED EXAMPLES;
CALIBRATION CONTRACT, DECISION PROCEDURE, WHAT NEVER COUNTS, SELF-CHECK untouched
per spec. `Challenge.raw_override_applied` added (default False for backward
compat with cached v5 payloads; prompt marks it REQUIRED so fresh outputs set it —
a missing field on the canary fails the probe by design). One disclosed deviation:
spec's "entry in key_risks" adapted to signal+summary (AnalystReport has no
key_risks field). PROMPT_VERSION → v5.1 (new sids; stale caches can't leak).

**Part C — probe 6/6 ALL-PASS** (single run after one transient provider timeout;
no prompt iteration needed):
ICICI/AXIS/ASIANPAINT HEALTHY override=False; SBIN/EICHERMOT HEALTHY override=False
(no widening — override stayed holstered without flags); CANARY BROKEN
override=True naming the exact blowoff fact ("blowoff_flag true (+12.0% in 5 days,
0.3% from 20-day high)"). First BROKEN ever produced. Suite: 38/38 green.

## What is blocked and why (update 3)

- **Regression on original 24:** 8/24 cached under v5.1 sids (SBIN + EICHERMOT both
  flip to correct buys under v5.1 — directional confirmation of the M1 fix).
  Then CodeCraft's Sonnet origin went hard-down with persistent 502s (their status:
  12.8% errors, 1 of 6 providers active). Four resume attempts across ~50 min all
  fail at the devil stage. Infra tuning applied: client timeout 30s → 120s,
  decider max_tokens 8192 → 16000, transient retry budget 3×8s → 5×60s backoff
  (matches their retry_after: 60). All crash-prevention, zero decision-logic change.
- **Official v5.1 eval on new-24:** 0/24, same blocker.
- Billing is resolved (key1 funded, ~98.9M); Dahl key stashed as fallback but its
  GLM endpoint times out under load and its Flash needs schema retry — CodeCraft
  remains primary. Resume both runs with one command each when the origin recovers.
- Suite: 38/38 mocked green (live technical deselected — provider down).

## Needed from user (either unblocks the evals)

1. Top up CodeCraft balance → `python scripts/run_eval_live.py --set v1`, then
   `python scripts/run_eval_live.py --set v5` (one-shot each, frozen gates).
2. AND/OR allocate pool tokens to the Dahl key (Dahl docs: keys start empty —
   current 402 is expected until allocation). If allocated, I validate GLM 5.3 /
   DeepSeek Flash schemas first; decider mapping (currently sonnet) stays frozen
   unless explicitly approved otherwise.
