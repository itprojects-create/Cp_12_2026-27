# Prereg: LLM direction honesty fix (manager hold-bias + deterministic sizing)

**Written:** 2026-10-09, BEFORE any code change or eval. No live sessions run under this prereg yet.
**Scope lock:** prompt + PM sizing only. No change to `trend_core*.py`, `gates.py` (frozen 2026-09-18), schemas/contract (additive-only), data providers, Devil, debate, risk panel.
**PROMPT_VERSION:** m9 -> m11 (new sids; m10 name reserved for retry pack to avoid collision).

## 1. Problem (from AGENT_REPORT §3 + baseline_and_m4 §2)

1. Manager prompt (`manager.py:16-18`) says "flat when most analysts are constructive is an error" -> trade rate 0.458->0.917/0.958, no-edge hold 0.667->0.08. Binding constraint upstream of Devil (Devil 72/72 HEALTHY live, cannot cure).
2. LLM sizes via conviction -> proposal.size_pct -> PM dec.size. Pooled Spearman(conviction,correct)=+0.033 (noise); gate calibration inverted 8/8 because flat-label over-trades carry size>0 vs correct holds size 0. Violates NEWW "LLM never sizes".
3. M3/M4 guardrails clip (trade back to 0.75) but don't fix direction.

## 2. Fix (code-level, deterministic, 0 tokens to build)

**F1 Manager honesty (prompt only):**
- Threshold: long/short requires mean conf >= 0.60 AND >=2-signal bullish/bearish margin (was 0.55 + simple majority).
- Flat explicitly valid: mean conf < 0.50 OR margin < 2 OR base-rate conflicts (index DOWN for long, UP for short) -> Hold/flat is correct, not error.
- Add base-rate sentence + falsifier sentence (one line each, same as retry m10): state index trend prior, state observation that would kill thesis.
- Mechanism_type classification unchanged.

**F2 Deterministic sizing (LLM never sizes):**
- `run_pm` llm-policy: ignore `dec.size` and `proposal.size_pct` magnitude. Size = FIXED_BASE 0.025 when action is buy/sell and all guardrails pass; ELEVATED momentum halves to 0.0125 (existing M3 rule, now on fixed base); STRESSED/BROKEN/flat/counter-trend -> 0.0 hold (existing rules unchanged).
- `run_trader` proposal.size_pct still returned (schema-required) but PM no longer trusts it. No schema change.
- Rationale audit tag appended: `[CODE SIZING: fixed 0.025, LLM size ignored]`.

## 3. Gates (no moves)

- Frozen `app/eval/gates.py` untouched.
- Unit gates (mocked, 0 tokens): manager prompt contains honesty clauses; llm-policy size is fixed regardless of PM-claimed 0.08 vs 0.02; flat/BROKEN/STRESSED/counter-trend still hold; trade-rate direction should fall, not rise (eval will confirm, not unit).
- Live eval explicitly DEFERRED: one-shot discipline + v3rd set contaminated (partially cached) + ~1.2M token cost. This ships as built + unit-tested, NOT evaluated — same honesty label as ship_report §"NOT yet claimed". Next official read needs a NEW blind set + G1-G5 (per evaluation_gates.md), not a rerun on v1/v5/v3rd.

## 4. Rollback

If unit tests fail or review rejects: revert manager.py/trader_risk.py/config.py to m9, delete this prereg's claim. No sessions under m11 exist yet, so no cache purge needed beyond new sids.
