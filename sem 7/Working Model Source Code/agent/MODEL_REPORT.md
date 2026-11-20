# QuantPlus Agentic OS — Model Report

**Date:** 2026-09-22 · **Service:** `agent-service` (FastAPI, `QuantPlus Agentic OS v1.0.0`)
**Models:** Analysts `deepseek-v4-pro-0813` · Deciders `claude-sonnet-5` (via CodeCraft OpenAI-compat gateway)
**Prompt versions run:** v5 → v5.1 → m3 · **Eval gates:** frozen 2026-09-18, unchanged throughout
**Test suite:** 52/52 green (2026-09-22) · **Live sessions scored:** 48+48 real sessions across two scenario sets + Devil probes

This file is the single record of **what we planned, what we built, what we measured, and what we tried to improve**.

---

## 1. What we planned

1. **Agentic pipeline ("Build Plan" Sec 4/8):** 5 parallel analysts → Bull/Bear debate → Research Manager synthesis → Devil's Advocate falsification → deterministic thesis versioning (HEALTHY→BROKEN) → Trader → 3-persona Risk panel → Portfolio Manager → `FinalDecision{action,size,rationale,thesis_version}`.
2. **Determinism where it matters:** numbers computed in code (features, regime, costs, versioning, guardrails); LLMs only interpret. No post-`as_of` leakage — PIT provider enforces `available_at <= as_of`; labels come only from post-`as_of` forward returns at scoring time.
3. **API contract first:** frontend touches ONLY `POST/GET /api/v1/sessions`, `GET /api/v1/theses`, `GET /api/v1/health`, and `WS /api/v1/sessions/{sid}/events` (typed stage frames, never raw tokens). Frozen Pydantic v2 schemas + generated `contract/schemas.json` + `frontend-client/client.ts`.
4. **Pre-registered eval discipline:** gates frozen 2026-09-18 *before* the first live run, never re-tuned to results:
   `n_decisive ≥ 8`, `accuracy ≥ 0.55`, `no-edge hold ≥ 0.40`, `trade_rate ∈ [0.20, 0.90]`, calibration directional (mean size correct > wrong). Horizon 20 trading days; decisive iff `|fwd| ≥ 4%`, else flat (hold expected). Paper PnL is cost-adjusted (0.21% round-trip) but report-only.
5. **Improvement roadmap M1–M4:** M1 Devil calibration (HEALTHY reachable but not automatic; BROKEN must exist) → M2 exhaustion gauge with Manager weighting → M3 VIX regime gating → M4 risk-budget. Each step: probe-gated, one official one-shot eval per scenario set, informative-report rule.

## 2. What we created (implemented)

| Layer | Files | What it does |
|---|---|---|
| Orchestration | `app/agents/graph.py` | `run_session()` with per-stage checkpoints + crash-resume (completed stages never re-billed), bounded debate rounds, wall-clock deadline, deterministic `record_thesis()` versioning, WS-replayable `session_events` |
| Analysts (luna) | `app/agents/analysts.py`, `technical.py`, `events_analyst.py`, `features.py` | Technical (deterministic feature block ~300 tok, not 20 raw OHLCV rows), Fundamentals, News, Macro, Events. `exhaustion_features()` (dist 20d lo/hi, ret_5d, ticker-own percentile threshold) injected via `exhaustion_line()` |
| Debate | `app/agents/debate.py` | Bull/Bear turns with confidence deltas, bounded rounds |
| Manager + Devil (sonnet) | `app/agents/manager.py` | Research Manager (weight-of-evidence synthesis + `mechanism_type` classification); Devil's Advocate v5.1 (calibration contract, duplicate-risk discard, symmetry check, RAW SIGNAL OVERRIDE, 3 worked examples) |
| Trader → Risk → PM | `app/agents/trader_risk.py` | Single sized proposal (10% max), 3 risk personas (agg/con/neu), PM with **deterministic code guardrails** (flat/BROKEN → hold/size-0; M3 VIX gate: STRESSED+momentum → hold, ELEVATED+momentum → halve, audit tag in rationale) |
| Data (PIT-safe) | `app/data/yfinance_provider.py`, `local_store.py`, `gnews_provider.py`, `gdelt_provider.py`, `events.py`, `sanitize.py`, `base.py`, `regime.py` | `YFinanceProvider.ohlcv()` (180d 1d span), delivery/breakout features, news with `available_at`, `regime_at()` on direct `^INDIAVIX` (CALM <50th / ELEVATED 50–85th / STRESSED ≥85th, <60 bars → CALM, total/never-raises) |
| Gateway | `app/gateway/codecraft.py` (+ `openrouter.py` fallback) | 5-key rotation, per-key pacing (1s), Retry-After honoring (cap 300s), 5×(2–60s) transient retry, 120s timeout, 402-quarantine per key / `OutOfFunds` only when ALL keys 402, circuit breaker, session (120k) + day (3M) token caps with SQLite-persisted ledger, per-call audit log |
| API + WS | `app/main.py`, `app/api/v1.py` | Sessions (deterministic sid = sha256(instrument\|as_of\|cfg), cached-done reuse, `force_rerun` clears checkpoints), theses + diff, health, WS live event stream (~10-min bounded poll) |
| Eval harness | `app/eval/run.py`, `gates.py`, `scenarios.py` (orig-24, 2023–24), `scenarios_v5.py` (new-24 `v5-2025-disjoint`, all-2025, zero of 8 contaminated tickers), `scenarios_v3rd.py` | Cached-session eval (reruns don't re-bill) → forward-return labels → cost-adjusted PnL → gate verdict → JSON report (`scenario_set` recorded) |
| Contract | `contract/openapi.json`, `contract/schemas.json`, `frontend-client/client.ts`, `scripts/export_contract.py`, `scripts/gen_ts_client.py` | Regenerated on schema change (M3 `mechanism_type`, v5.1 `raw_override_applied`); contract test refreshes client, no hand edits |
| Ops/scripts | `scripts/run_eval_live.py`, `probe_devil_reachability.py`, `diagnose_exhaustion_thresholds.py`, `diagnose_history_window.py`, `e2e_no_frontend.py` | One-shot live evals, 5/6-case Devil probe (incl. BROKEN canary), exhaustion diagnostics, no-frontend E2E |
| Persistence | `app/db.py`, `app/config.py`, `app/log.py`, `docker-compose.yml` | SQLite (sessions, checkpoints, theses, events, usage_daily) + optional Postgres/Mongo; central `Settings` (models, caps, key maps); structured session log |

Key design fixes along the way: compact feature block (raw-OHLCV tables burned reasoning budgets → `finish=length` empties); decider `max_tokens` 8192 → 16000 (long v5.1 devil prompt truncated); `Thesis.mechanism_type` / `Challenge.raw_override_applied` Pydantic-defaulted (not required) for checkpoint backward-compat; strict-`<` VIX ranking (flat stretches → CALM, never 100).

## 3. Evaluation methodology

- **Sets:** orig-24 (`v1-2023-2024`, 2023-07→2024-12) and new-24 (`v5-2025-disjoint`, all-2025 windows, built 2026-09-19 *before* any v5 run, disjoint tickers/windows from orig-24).
- **Labels:** `forward_return()` from post-`as_of` closes only; `long ≥ +4% / short ≤ −4% / else flat`. Agents never see post-`as_of` data.
- **Metrics:** accuracy on decisive only, `P(hold|flat)`, trade rate, calibration direction (mean size correct vs wrong), cost-adjusted paper PnL. Verdict INCONCLUSIVE if `n_decisive < 8`, else PASS only if all checks pass.
- **Rule:** one official one-shot eval per set per version; no re-runs to chase numbers; resume-from-checkpoint only on infra crashes (re-bills remainder only).

## 4. Results we got

### 4.1 Official evals (frozen gates, one shot each)

| # | Report JSON | Prompt / set | n_dec | acc (≥0.55) | hold (≥0.40) | trade (0.20–0.90) | calib | PnL | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `eval_report_20260918T165134Z.json` | pre-v5 / orig-24 | 12 | 0.333 | 0.583 | 0.625 ✓ | ✗ | −0.0046 | **FAIL** |
| 2 | `eval_report_20260919T133151Z.json` | v4 / orig-24 | 12 | 0.333 | 0.667 | 0.458 ✓ | ✗ | +0.0047 | **FAIL** |
| 3 | `eval_report_20260919T160958Z.json` | **v5 / new-24** | 13 | 0.385 | 0.182 | 0.875 ✓ | ✗ (0.0198 vs 0.0258 inv.) | −0.0047 | **FAIL** |
| 4 | `eval_report_20260920T074259Z.json` | **v5.1 / orig-24** (regression) | 12 | 0.500 | 0.083 | 0.958 ✗ | ✗ | −0.0063 | **FAIL** |
| 5 | `eval_report_20260920T092702Z.json` | **v5.1 / new-24** (official) | 13 | 0.385 | 0.091 | 0.917 ✗ | ✗ | −0.0062 | **FAIL** |
| 6 | `eval_report_20260920T113129Z.json` | **m3 / new-24** | 13 | 0.231 | 0.182 | 0.750 ✓ | ✗ | −0.0104 | **FAIL** |
| 7 | `eval_report_20260920T164633Z.json` | **m3 / orig-24** (via 2 crash-resumes) | 12 | 0.333 | 0.250 | 0.750 ✓ | ✗ | −0.0032 | **FAIL** |

**No PASS to date.** Every run clears `n_decisive_ok` but fails accuracy and calibration; hold-rate and trade-rate trade off against each other across versions (see §5). At n_decisive ≈ 12–13, 2 thesis flips swing the headline — single-run accuracy is noise-dominated.

### 4.2 Devil / thesis distribution (the M1 signal)

- v4 orig-24: HEALTHY only 4/24 (veto-everything era).
- v5 new-24: **24/24 HEALTHY, 0 BROKEN** — pendulum overshoot to trade-everything (hold 0.667→0.182, trade 0.458→0.875).
- v5.1 probe (CodeCraft, 2026-09-20): **6/6 ALL-PASS** — 5/5 originals HEALTHY with override holstered + constructed canary (LONG + hand-built blowoff ret_5d +12%, dist_hi +0.3%) **BROKEN** with `raw_override_applied=true`, first BROKEN ever (v2/v4/v5 never fired it).
- v5.1 live: **48/48 real sessions HEALTHY, 0 overrides** — BROKEN reachable in principle, empirically inert (flag base rate 1/48: ONGC LONG+flush, correctly out of scope since override fires only LONG+blowoff / SHORT+flush).
- m3 live: **24/24 HEALTHY both sets** (72/72 HEALTHY across v5.1+m3; BROKEN exists only in the canary).

### 4.3 Production regime split (m3, operative ~126-bar window)

New-24 CALM=15 / ELEVATED=4 / STRESSED=5; orig-24 CALM=11 / ELEVATED=7 / STRESSED=6. Cutoff validation on full 2022–2025 history: CALM=29 / ELEVATED=11 / STRESSED=8 (election-spike May–Jun 2024, Jan/Apr/May 2025 land STRESSED). Manager actually classifies mechanism (MOMENTUM 10+11, EVENT_DRIVEN 8+7, rest MEAN_REVERSION/OTHER on flat theses).

## 5. Improvements we tried (and what each measured)

1. **v5 — M1 Devil recalibration + M2 exhaustion gauge + fresh disjoint set** (`data/v5_report_20260919.md`):
   Calibration contract + duplicate-risk discard + symmetry check; `exhaustion_features()` (ticker-own 90th-pct threshold, PIT-safe) wired into Technical prompt as signal+summary (spec deviation disclosed: `AnalystReport` has no `key_risks` field). New 24-scenario 2025 set, harness `--set v1|v5`. Probe 5/5 HEALTHY first-try. Effect: accuracy 0.333→0.385 but hold collapsed and trade-rate hit bound; conviction inverted; Devil 24/24 HEALTHY — overshoot diagnosed, M3 flagged as highest-signal untouched lever.
2. **v5.1 — M1 reachability fix: raw cross-wire + few-shot anchoring** (`data/v5_1_report_20260920T092850Z.md`):
   `RawExhaustionSignals` pass-through (Technical computes once → checkpoint → Devil payload field, never recomputed; pre-v5.1 renders "unavailable"), RAW SIGNAL OVERRIDE + 3 worked examples (contract/procedure/self-check byte-untouched), 6-case probe with canary. Effect: 6/6 probe incl. first BROKEN; live accuracy flat (0.385→0.385 new-24; 0.333→0.500 orig-24 regression) while over-trading worsened past the gate (0.917/0.958) — proved the binding constraint is upstream of the Devil (Manager/Trader almost never holds).
3. **M3 — deterministic VIX regime gate, code-level not prompt-level** (`data/m3_report_20260920T164933Z.md`):
   Direct `^INDIAVIX` classifier + `Thesis.mechanism_type` (one disclosed deviation: default OTHER for probe/checkpoint compat) + `run_pm` gate (STRESSED+momentum → hold; ELEVATED+momentum → halve; else passthrough; None→CALM; tagged rationale). 4 regime + 7 gate tests; suite 50/50. Effect: **fixed the trade-rate breach** (0.917→0.75, 0.958→0.75) but accuracy fell on both sets (gated sessions went 2 OK / 1 real cost — SBIN correct long blocked / rest loss-reduced-or-neutral; the fall is prompt re-sampling + n≈12 noise, mostly extra flat theses not gate holds). Audited guardrail, not a direction-quality fix.
4. **M2 diagnostics (Part 0, report-only):** `diagnose_exhaustion_thresholds.py` on 48 sessions — fire rates @90th 4/48 (8%), @80th 12/48 (25%), @75th 13/48 (27%); root cause found: Technical's 60-bar slice leaves <60 bars pre-`as_of` history so production falls back to flat 8.0% (only ONGC −8.37% ever flagged). Follow-through since landed in code: 80th-percentile re-tune + history-window fix (`features.py`), separately testable, pending its own official eval. **Contamination caveat:** new-24 has now been looked at 3× (v5→v5.1→m3) — direction-finding only; next round needs a fresh unseen third set before citing any number.
5. **Infra hardening (zero decision-logic change):** client timeout 30→120s, decider max_tokens 8192→16000 (sonnet `finish=length` empties), retry 3×8s → 5×(2–60s) backoff, deciders prefer-but-don't-pin funded key (survived idx0/idx1 502 + idx4 402 flap), `OutOfFunds` only when ALL keys 402, crash-resume proven (orig-24 m3 finished via 2 resumes after 520/timeout kills of sessions 18/19), day-cap raised with notes to allow one full eval (~1.2M) + headroom. Spend: v5 ≈1.5M; v5.1 ≈2.33M/6M cap; m3 ≈4.81M/6M (new-24 ≈1.2M, orig-24 ≈1.17M across resumes).

## 6. Bottom line and next steps

- **Built:** a working, PIT-safe, checkpoint-resumable multi-agent trading OS with audited LLM ledger, deterministic guardrails, frozen contracts, 52/52 tests, and a pre-registered eval harness over two 24-scenario sets.
- **Measured:** 7/7 official evals FAIL; Devil evolved veto-everything → auto-HEALTHY → reachable-but-inert BROKEN; M3 gate restores trade-rate discipline but doesn't fix direction or calibration; accuracy at n≈12 is noise-dominated and the gate trades one error type for another.
- **Next, in order:** (1) fresh third scenario set before citing numbers; (2) M2 slice-depth + 80th-percentile threshold official eval (Part 0 shows 25% vs 8% fire); (3) M4 risk-budget only after those. No M4 work touched this round.

## Appendix — reproduce & files

- Tests: `python -m pytest tests -q` (52 passed). Per-area: `test_m3_gate.py` (7 gate), `test_regime.py` (4), `test_exhaustion.py`, `test_pit.py`, `test_full_session.py`, `test_eval.py`, `test_api_ws.py`, …
- Evals: `python scripts/run_eval_live.py --set v1|v5` (frozen `app/eval/gates.py`); probe: `python scripts/probe_devil_reachability.py`; diagnostics: `python scripts/diagnose_exhaustion_thresholds.py`, `python scripts/diagnose_history_window.py`.
- Reports: `data/v5_report_20260919.md`, `data/v5_1_report_20260920T092850Z.md` (+ `v5_1_report_20260919_interim.md`), `data/m3_report_20260920T164933Z.md`, `data/eval_report_*.json` (7), `data/delivery_features.csv`, `data/sessions.log`, `data/quantplus.db`.
