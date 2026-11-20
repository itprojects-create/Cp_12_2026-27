# W4 — Acceptance report (Jev event intelligence + Mercury research tools)

Generated: 2026-11-14T08:28:47.860313+00:00 · Verdict: **ENGINEERING PASS / EVIDENCE
PARTIAL_DATA_BLOCKED**

## 1. What W4 delivered

| Criterion | Status | Evidence |
|---|---|---|
| Provider issuer verified before any use | **PASS** | ExperientialLabs org key proven (vendor docs + prod config); gateway/Bearer/401 semantics recorded; entitlement `GET /v1/models` HTTP 200 (307 models, `jev-latest` callable) |
| Offline contract suite, no credentials needed | **PASS** | 78/78 tests in `tests/test_research_v3_events_ai.py` (fake transports only) |
| Live smoke, tiny budget, redacted | **PASS** | Jev: 1 call HTTP 200 `jev-latest` 810 ms 616/110 tok cost 0.0; Mercury: 2 calls HTTP 200 `mercury-3` (first `max_tokens=8` consumed by reasoning tokens, empty visible content — honestly documented); ~$0 total spend |
| Strict validation + security tests | **PASS** | PIT/timestamp/hash/injection gates; NaN-rejecting parse; retry/circuit/budget fail-closed paths; secret-hygiene tests; no-trade AST scans |
| Typed event evidence + semantic ids | **PASS** | `events_ai/evidence/1`, `classification/1`; 24-row manifest with ids/hashes; capture-metadata excluded from `event_id` |
| Goldset with label-quality report | **PARTIAL — synthetic only** | 24 authored fixtures, `ENGINEERING_CHECK_SYNTHETIC` metrics; real goldset `GOLDSET_HOLDOUT_UNAVAILABLE` (no lawful contemporaneous corpus) + preregistered minimum quality policy + forward capture protocol |
| Paired financial ablation A–F | **PARTIAL — data blocked** | Arm A verified by hash reevaluation (`UNCHANGED`); B–E `HISTORICAL_EVENT_ABLATION_BLOCKED`; F contextual-only; classification engineering check recorded |
| Jev OFF ⇒ numeric control unchanged | **PASS** | hash reevaluation UNCHANGED; `quantlab`-never-imports-`events_ai` AST test; verifier imports quantlab/warehouse/lab only |
| Mercury bounded integration | **PASS (engineering)** | frozen 4-tool allowlist, deterministic executors, grounding check, idempotency, budget 8/session, default-disabled, fail-closed client; not wired into production paths |
| Provider contract + security document | **PASS** | `wave4_provider_contract_and_security.md` (embeds redacted smoke evidence + rotation advice) |
| Regression discipline | **PASS** | pre-W4 prod run `5 failed/594 passed` (same as W3 baseline), 5/5 `KNOWN_PREEXISTING`; one W4-introduced prod-only failure (frozen-hash test reading a reports path absent in prod checkouts) found and FIXED via a layout-aware skip; W4 run 2: `6 failed, 670 passed, 1 skipped, 22 warnings in 328.37s (0:05:28)` with 5/5 pre-existing unchanged and one extra failure classified `FLAKY_LIVE_LLM` (live-provider `finish_reason=length`, zero W4 frames, passed in both earlier runs — see `wave4_regression_and_prod_failures.md` §3) |

## 2. Suite evidence

- Dev full suite: `651 passed in 45.57s` (expectation 651 passed = 573 + 78).
- Production full suite after byte-identical sync: `6 failed, 670 passed, 1 skipped, 22 warnings in 328.37s (0:05:28)` — the same 5
  pre-existing failures, plus one live-LLM flake classified in
  `wave4_regression_and_prod_failures.md` §3 (not W4-introduced), plus `1
  skipped` = the frozen-hash contracts cross-check, skipped by design in a prod
  checkout without a reports tree (W4-introduced prod failure from run 1, fixed).
- `typesafe_direct` lane: **NOT_TESTED** (no key exists — recorded as such).

## 3. Operator actions required

1. **Rotate the chat-pasted Jev key** (`xpl_…355b`) — exposed in chat; never
   used by any code (server fingerprint differs), but treat it as burned.
2. Provide a TypeSafe-issued key to test the `typesafe_direct` lane (optional;
   adapter ready).
3. Fund/approve a contemporaneous official-announcement capture pipeline to
   unblock the real goldset and Arms B–E (forward protocol preregistered).

## 4. Not claimed

No financial performance, alpha, prediction-skill or real-classification-quality
claim is made anywhere in the W4 artifacts. Live smokes prove interoperability
only. Synthetic metrics are labelled `ENGINEERING_CHECK_SYNTHETIC`.
