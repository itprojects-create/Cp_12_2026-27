# Prereg: Ground the deciders in the structured evidence (manager + debate)

**Written:** 2026-10-10, BEFORE any code change or eval under this prereg.
**Scope lock:** prompt *inputs* only (`app/agents/_util.py`, `manager.py`, `debate.py`)
+ `PROMPT_VERSION` bump. No change to `trend_core*.py`, `gates.py` (frozen
2026-09-18), schemas/contract, data providers, Devil logic, Trader/Risk/PM
guardrails, or `DIRECTION_POLICY`.

**PROMPT_VERSION:** m11 -> m12 (new session ids; no cached session is reused).

## 1. Root cause (the bug this fixes)

Every analyst already emits a structured `signals[]` list (`name`, `value`,
`direction ∈ bullish|bearish|neutral`) plus a `confidence` — 15-20 signals per
session, e.g. `technical: trend_vs_sma20=+2.53 bullish, momentum_20d=+7.78
bullish, ...`. `grep -rn "\.signals" app/` returns **nothing**: the signals were
computed, persisted in checkpoints, and then **never read by any decision
stage**. They were write-only.

The Research Manager prompt (`manager.py`) mandates a *weight-of-evidence* rule:

> "Tally first: mean analyst confidence, and bullish vs bearish vs neutral
>  signal counts." … "Choose long only when bullish evidence clearly outweighs
>  (mean conf >= 0.60 with at least 2 more bullish than bearish signals)."

but the orchestration passed the Manager — and the Bull/Bear debate — **only the
analyst `summary` prose** (`.summary`, no `signals`). The model was therefore
asked to compute a signal-count margin it was never shown. It can only guess:
- under m9 (no hard margin) that guessing produced conviction-driven
  over-trading (trade rate 0.875-0.958, no-edge hold 0.08);
- under m11 (hard `margin >= 2`) the ungrounded margin can never be truthfully
  established, so the model defaults to the safe branch — the fresh v6 run held
  on 11/12 completed scenarios, i.e. near always-hold, which is 0 accuracy on
  decisive labels by construction.

So the headline "LLM has no directional skill" is partly an artifact of the LLM
never being given the evidence it was told to weigh. This is fixable plumbing,
not a prompt tune (which the board already ruled out).

## 2. Fix (deterministic, code-level, 0 tokens to build)

`_util.evidence_ledger(reports)` renders, per analyst, the confidence, the full
`signals` list (`name=value direction`), the summary, and a **code-computed,
authoritative TALLY**: `bullish/bearish/neutral` counts, `signal_margin`
(bullish-bearish), `mean_conf`, analyst count. The Manager and the Bull/Bear
debate digests now use it. The Manager prompt now says the TALLY is computed in
code and must be used as given (never recounted/guessed) — same style as the M3
VIX gate ("numbers in code, LLM interprets").

No schema change (signals already exist); no contract change; additive only.

## 3. Gates (no moves) + test plan

- Frozen `app/eval/gates.py` untouched.
- Unit gates (mocked, 0 tokens, `tests/test_manager_evidence.py`): the ledger
  contains every signal; the TALLY counts/margin/mean_conf are exact and
  deterministic; the Manager user prompt carries the ledger + TALLY; the Manager
  system prompt tells the model the TALLY is authoritative.
- Live eval explicitly DEFERRED (one-shot discipline; v6 is partially cached and
  unlabeled-complete). This ships built + unit-tested, labeled NOT evaluated —
  same honesty rule as prior prompt fixes. The next official read needs the
  remaining v6 scenarios (or a fresh set) under m12, recorded as-is.

## 4. Rollback

Revert `_util.py`/`manager.py`/`debate.py`/`config.py` to m11 and delete this
prereg's claim. No m12 sessions exist until an eval is run, so no cache purge is
needed beyond the version hash.
