# QuantPlus Agentic OS — Full Agent Report: What We Did, Every Result, Why It Failed

**Date:** 2026-10-05 · **Service:** `agent-service` (FastAPI, `QuantPlus Agentic OS v1.0.0`)
**Models:** Analysts `deepseek-v4-pro-0813` · Deciders `claude-sonnet-5` (via CodeCraft OpenAI-compat gateway)
**Prompt versions:** pre-v5 → v4 → v5 → v5.1 → m3 · **Current `PROMPT_VERSION=m3`** (`app/config.py`)
**Eval gates:** frozen 2026-09-18, never re-tuned (`app/eval/gates.py`)
**Test suite:** 52/52 green · **Live sessions:** 96+ real sessions (48 v5/v5.1 + 48 m3) + Devil probes
**DB:** `data/quantplus.db` (SQLite) + optional Postgres/Mongo (`docker-compose.yml`)

This file consolidates `MODEL_REPORT.md`, `data/v5_report_20260919.md`, `data/v5_1_report_20260920T092850Z.md` (+ interim), `data/m3_report_20260920T164933Z.md`, all 7 `data/eval_report_*.json`, code state, and failure analysis.

---

## 1. What we built (system)

### 1.1 Agent pipeline (`app/agents/graph.py:81-192` `run_session()`)

```
5 parallel analysts (luna) -> Bull/Bear debate (luna, 2 rounds, bounded)
-> Research Manager (sonnet) -> Devil's Advocate (sonnet)
-> deterministic record_thesis() versioning (HEALTHY→BROKEN)
-> Trader (luna) -> 3-persona Risk panel (luna) -> Portfolio Manager (sonnet + code guardrails)
-> FinalDecision{action,size,rationale,thesis_version}
```

Per-stage checkpoints + crash-resume (completed stages never re-billed), wall-clock deadline, bounded debate, WS-replayable `session_events`. Session id deterministic: `sha256(instrument|as_of|cfg)` (`graph.py:14-16`, `app/api/v1.py:14-22`); cached-done reuse, `force_rerun` clears checkpoints.

| Layer | Files | What it does |
|---|---|---|
| Analysts | `analysts.py`, `technical.py`, `events_analyst.py`, `features.py` | Technical (compact ~300-tok feature block `describe()`, not 20 raw OHLCV rows that caused `finish=length` empties), Fundamentals (tape+ratios), News (GDELT hist / gnews live, sanitized), Macro (^NSEI+^INDIAVIX), Events (earnings surprise / upcoming). All PIT-filtered, return frozen `AnalystReport`. `exhaustion_features()` + `exhaustion_line()` injected into Technical |
| Debate | `debate.py` | Bull/Bear turns with `confidence_delta`, converge-exit if both <0.05 |
| Manager + Devil | `manager.py` | Manager: weight-of-evidence synthesis + `mechanism_type` classification. Devil v5.1: calibration contract, duplicate-risk discard, symmetry check, RAW SIGNAL OVERRIDE, 3 worked examples |
| Trader→Risk→PM | `trader_risk.py` | Single sized proposal (10% max `MAX_POSITION_PCT`), 3 risk personas (agg/con/neu), PM with **deterministic code guardrails**: flat/BROKEN→hold/size-0; M3 VIX gate STRESSED+momentum→hold, ELEVATED+momentum→halve, audit tag in rationale |
| Data (PIT-safe) | `data/yfinance_provider.py`, `local_store.py`, `gnews_provider.py`, `gdelt_provider.py`, `events.py`, `sanitize.py`, `base.py`, `regime.py` | `YFinanceProvider.ohlcv()` (180d 1d span, disk cache `data/yf_cache/`, `available_at<=as_of` enforced, 15-min delay guard), delivery/breakout features, news with `available_at`, `regime_at()` on direct `^INDIAVIX` (CALM<50th / ELEVATED 50-85th / STRESSED≥85th, <60 bars→CALM, total/never-raises) |
| Gateway | `gateway/codecraft.py` (+ `openrouter.py` fallback) | 5-key rotation, per-key pacing 1s, Retry-After honoring cap 300s, 5×(2-60s) transient retry, 120s timeout, 402-quarantine per key / `OutOfFunds` only when ALL keys 402, circuit breaker, session 120k + day 6M caps with SQLite-persisted ledger, per-call audit log |
| API+WS | `main.py`, `api/v1.py` | Sessions, theses+diff, health, WS live event stream (~10-min bounded poll, typed frames only) |
| Eval harness | `eval/run.py`, `gates.py`, `scenarios.py` (orig-24 2023-24), `scenarios_v5.py` (new-24 `v5-2025-disjoint`), `scenarios_v3rd.py` (`v3rd-2026-clean`, built never run) | Cached-session eval (reruns don't re-bill) → `forward_return()` from post-`as_of` closes only → labels → cost-adjusted PnL (0.21% round-trip) → gate verdict → JSON report |
| Contract | `contract/openapi.json`, `contract/schemas.json`, `frontend-client/client.ts`, `scripts/export_contract.py`, `gen_ts_client.py` | Regenerated on schema change (M3 `mechanism_type`, v5.1 `raw_override_applied`); contract test refreshes client, no hand edits |
| Ops/scripts | `run_eval_live.py`, `probe_devil_reachability.py`, `diagnose_exhaustion_thresholds.py`, `diagnose_history_window.py`, `e2e_no_frontend.py` | One-shot live evals (`--set v1|v5|v3`), 5/6-case Devil probe incl. BROKEN canary, exhaustion diagnostics, no-frontend E2E |
| Persistence | `db.py`, `config.py`, `log.py` | SQLite tables `sessions,theses,session_events,checkpoints,usage_daily`; central `Settings` (models, caps, key maps); structured `data/sessions.log` |

Frozen Pydantic v2 schemas (`app/schemas.py`): `Signal`, `Evidence`, `AnalystReport`, `DebateTurn`, `Thesis{+mechanism_type=OTHER default}`, `Challenge{+raw_override_applied=False default}`, `RawExhaustionSignals`, `TradeProposal`, `RiskVerdict`, `FinalDecision`, `SessionRequest`, `StageEvent`.

Design fixes: compact feature block; decider `max_tokens` 8192→16000; `mechanism_type`/`raw_override_applied` defaulted for checkpoint compat; strict-`<` VIX ranking (flat→CALM).

### 1.2 What we did, in order

1. **Pre-v5/v4 baseline:** pipeline + frozen gates 2026-09-18 + orig-24 set. Ran 2 evals (see §2).
2. **v5 (2026-09-19, `data/v5_report_20260919.md`):** M1 Devil recalibration (contract+discard+symmetry) + M2 `exhaustion_features()` (ticker-own 90th-pct, PIT-safe) wired via `exhaustion_line()` + fresh disjoint new-24 set (2025, zero of 8 contaminated tickers, built before any v5 run). Probe 5/5 HEALTHY first-try. Official new-24 eval + partial v1 regression (halted 10/24 by 402 billing).
3. **v5.1 interim (2026-09-19):** Part A `RawExhaustionSignals` pass-through (Technical computes once→checkpoint `exhaustion`→Devil payload, never recomputed), Part B RAW SIGNAL OVERRIDE + 3 worked examples (contract/procedure/self-check byte-untouched), Part C 6-case probe with canary. Blocked by CodeCraft Sonnet 502s; infra hardening (timeout 30→120s, retry 3×8s→5×(2-60s)).
4. **v5.1 official (2026-09-20):** probe 6/6 on CodeCraft + regression orig-24 (24/24) + official new-24 (24/24). Infra fix: deciders prefer-but-don't-pin funded key, `OutOfFunds` only when all keys 402.
5. **M3 (2026-09-20, `data/m3_report_20260920T164933Z.md`):** deterministic VIX regime gate (code-level, not prompt-level): direct `^INDIAVIX` classifier + `Thesis.mechanism_type` + `run_pm` gate + 4 regime + 7 gate tests. Part 0 exhaustion diagnostic (report-only). Two evals (new-24 + orig-24 via 2 crash-resumes after 520/timeout kills).
6. **M2 rehab (landed in code, pending official eval):** 80th-pct re-tune + history-window fix (`features.py:61` quantile 0.80, `technical.py:31` dedicated 400-bar `df_hist` pull, same cache key, zero extra network). Separately testable, no official eval yet.
7. **v3rd set built 2026-09-20 (`scenarios_v3rd.py`):** `v3rd-2026-clean`, 24 scenarios 2026-01..07, each ticker once, no pair overlap with v1/v5, regime mix CALM=4/ELEVATED=12/STRESSED=8. **Never evaluated** — reserved as fresh unseen set.

No M4 (risk-budget) work touched.

---

## 2. Every result (official, frozen gates, one-shot each)

Gates: `n_decisive≥8` else INCONCLUSIVE, `accuracy≥0.55`, `no-edge hold≥0.40`, `trade∈[0.20,0.90]`, calibration directional (mean size correct>wrong). Horizon 20d; decisive iff `|fwd|≥4%` else flat. PnL cost-adjusted report-only.

| # | Report JSON | Prompt / set | n_dec | acc | hold | trade | calib | PnL | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `eval_report_20260918T165134Z.json` | pre-v5 / orig-24 | 12 | 0.333 | 0.583 ✓ | 0.625 ✓ | ✗ | −0.0046 | **FAIL** |
| 2 | `eval_report_20260919T133151Z.json` | v4 / orig-24 | 12 | 0.333 | 0.667 ✓ | 0.458 ✓ | ✗ | +0.0047 | **FAIL** |
| 3 | `eval_report_20260919T160958Z.json` | **v5 / new-24** | 13 | 0.385 | 0.182 ✗ | 0.875 ✓ | ✗ (0.0198 vs 0.0258 inv.) | −0.0047 | **FAIL** |
| 4 | `eval_report_20260920T074259Z.json` | **v5.1 / orig-24** | 12 | 0.500 | 0.083 ✗ | 0.958 ✗ | ✗ | −0.0063 | **FAIL** |
| 5 | `eval_report_20260920T092702Z.json` | **v5.1 / new-24** | 13 | 0.385 | 0.091 ✗ | 0.917 ✗ | ✗ | −0.0062 | **FAIL** |
| 6 | `eval_report_20260920T113129Z.json` | **m3 / new-24** | 13 | 0.231 | 0.182 ✗ | 0.750 ✓ | ✗ | −0.0104 | **FAIL** |
| 7 | `eval_report_20260920T164633Z.json` | **m3 / orig-24** | 12 | 0.333 | 0.250 ✗ | 0.750 ✓ | ✗ | −0.0032 | **FAIL** |

**No PASS to date.** Every run clears `n_decisive_ok` but fails accuracy + calibration; hold/trade trade off across versions. At n≈12–13, 2 flips swing headline — single-run accuracy noise-dominated.

Per-run notes:
- **#3 v5 new-24:** correct decisive TCS sell, INFY sell, TITAN buy, RELIANCE buy, ONGC buy. Misses: POWERGRID sell/+13.3%, ICICI hold/+10.0%, AXIS buy/−5.4%, HCLTECH buy/−10.9%, WIPRO buy/−10.4%, ASIANPAINT sell/+8.1%, SUNPHARMA sell/+4.1%, ULTRACEMCO sell/+6.6%.
- **#4 v5.1 orig-24:** acc 0.333→0.500 but hold collapsed, trade breached bound — trade-everything.
- **#5 v5.1 new-24:** acc flat 0.385→0.385, hold 2/11→1/11, trade across gate line.
- **#6/#7 m3:** trade back in bounds (0.75/0.75) but acc fell (see §3.4 why this is resampling, not gate damage).

### 2.1 Devil / thesis distribution (the M1 signal)

- v4 orig-24: HEALTHY only 4/24 (veto-everything era).
- v5 new-24: **24/24 HEALTHY, 0 BROKEN** — overshoot to trade-everything.
- v5.1 probe (CodeCraft 2026-09-20): **6/6 ALL-PASS** — 5/5 HEALTHY override holstered + canary (LONG + blowoff ret_5d +12%, dist_hi +0.3%) **BROKEN** with `raw_override_applied=true`, first BROKEN ever.
- v5.1 live: **48/48 HEALTHY, 0 overrides** — BROKEN reachable in principle, empirically inert (flag base rate 1/48: ONGC LONG+flush, correctly out of scope since override fires only LONG+blowoff / SHORT+flush).
- m3 live: **24/24 HEALTHY both sets** (72/72 HEALTHY across v5.1+m3; BROKEN only in canary).

### 2.2 Regime split (m3, operative ~126-bar window)

New-24 CALM=15 / ELEVATED=4 / STRESSED=5; orig-24 CALM=11 / ELEVATED=7 / STRESSED=6. Full-history validation 2022–2025: CALM=29 / ELEVATED=11 / STRESSED=8 (May–Jun 2024 election spike, Jan/Apr/May 2025 land STRESSED). Manager classifies mechanism: MOMENTUM 10+11, EVENT_DRIVEN 8+7, rest MEAN_REVERSION/OTHER on flat theses.

Gate effect: new-24 2/10 momentum gated (NTPC STRESSED block→hold OK; TITAN ELEVATED halve 0.02→0.01 OK). Orig-24 6/11 gated (NTPC block OK; KOTAK block avoided loss but still MISS; SBIN block of CORRECT long = real cost; ULTRACEMCO/HCLTECH/ADANIENT halves loss-reduced but still MISS).

### 2.3 Exhaustion diagnostic (M2 Part 0, report-only)

`diagnose_exhaustion_thresholds.py` on 48 sessions: fire @90th 4/48 (8%), @80th 12/48 (25%), @75th 13/48 (27%). Root cause: Technical 60-bar slice leaves <60 bars pre-`as_of` → production falls back to flat 8.0% (only ONGC −8.37% ever flagged). Fix landed (80th + 400-bar `df_hist`), pending official eval.

### 2.4 Probes, tests, spend, infra

- Probes: v5 5/5 HEALTHY; v5.1 6/6 incl. first BROKEN. Suite 38→39→50/50→52/52 (`test_m3_gate.py` 7, `test_regime.py` 4, `test_exhaustion.py`, `test_pit.py`, `test_full_session.py`, `test_eval.py`, `test_api_ws.py`, …).
- Spend: v5 ≈1.5M; v5.1 ≈2.33M/6M cap; m3 ≈4.81M/6M (new-24 ≈1.2M, orig-24 ≈1.17M across resumes). `.env` day cap now 6M.
- Hardening (zero decision-logic change): timeout 30→120s, decider max_tokens 8192→16000 (sonnet `finish=length` empties), retry 3×8s→5×(2–60s), deciders prefer-but-don't-pin funded key (survived idx0/idx1 502 + idx4 402 flap), `OutOfFunds` only when ALL keys 402, crash-resume proven (orig-24 m3 via 2 resumes after 520/timeout kills sessions 18/19), day-cap raised to allow one full eval (~1.2M)+headroom.
- Contamination caveat: new-24 looked at 3× (v5→v5.1→m3) — direction-finding only; next round needs fresh v3rd set before citing numbers.

---

## 3. Why the model failed (root causes)

1. **Manager almost never holds; Devil almost never breaks — no brake on bad trades.** Manager prompt (`manager.py:10-35`) mandates `flat ONLY for genuine ambiguity`, `flat when constructive is an error`. Trade rate 0.458 (v4) → 0.875 (v5) → 0.917/0.958 (v5.1 breach). Devil 48/48 + 24/24 HEALTHY live, 0 WEAKENED/BROKEN, 0 overrides. Binding constraint is upstream of Devil — no Devil patch can cure a Manager/Trader that won't hold.
2. **Exhaustion gauge invisible in production.** 60-bar slice → 8% fallback → 1/48 flags. Buys-into-decline (AXIS/HCLTECH/WIPRO) and sells-into-rallies (POWERGRID +13.3%, ICICI +10%) pass undebated. Threshold + slice-depth fix landed but unevaluated.
3. **Momentum without regime context.** Pre-M3 nothing blocked corrective tapes. M3 gate restores trade-rate discipline (0.75 back in bounds) but doesn't fix direction: gated 2 OK / 1 real cost (SBIN correct long blocked in STRESSED) / rest neutral-or-loss-reduced. Audited guardrail, not direction-quality fix.
4. **Calibration inverted every run.** Mean size(correct) < mean size(wrong). Risk panel + PM size on conviction/challenge that carry no edge; PM guardrails only clip flat/BROKEN and VIX-momentum, not overconfidence.
5. **Small-n noise + reuse.** n_decisive 12–13 → 2 flips swing headline. M3 accuracy fall is prompt re-sampling (TCS#1, ICICI#7→flat; EICHERMOT→flat) + fresh sids, not gate holds. New-24 reused 3× — cannot cite numbers until v3rd clean read.

---

## 4. Improvements tried and measured effect

1. **v5 (M1 recal + M2 gauge + disjoint set):** acc 0.333→0.385 but hold 0.667→0.182, trade 0.458→0.875, conviction inverted, Devil 24/24 HEALTHY — overshoot diagnosed, M3 flagged highest-signal untouched lever.
2. **v5.1 (raw cross-wire + few-shot):** 6/6 probe incl. first BROKEN; live acc flat (0.385→0.385 new-24; 0.333→0.500 orig-24 regression) while over-trading worsened past gate — proved binding constraint upstream of Devil.
3. **M3 (deterministic VIX gate, code not prompt):** fixed trade-rate breach (0.917→0.75, 0.958→0.75) but acc fell both sets via resampling noise + extra flat theses, not gate holds. Not a direction fix.
4. **M2 diagnostics + rehab (code, pending eval):** 80th fires 25% vs 8% at 90th; history-window fix makes real branch the norm. Needs its own official eval on v3rd set.
5. **Infra hardening:** no decision-logic change; enabled unattended evals + crash-resume proof.

---

## 5. Bottom line and next steps

- **Built:** working PIT-safe checkpoint-resumable multi-agent OS with audited ledger, deterministic guardrails, frozen contracts, 52/52 tests, pre-registered harness over two 24-scenario sets + one clean reserve set.
- **Measured:** 7/7 FAIL; Devil veto-everything→auto-HEALTHY→reachable-but-inert; M3 restores discipline but not direction/calibration; accuracy at n≈12 noise-dominated.
- **Next, in order:** (1) official eval on fresh `v3rd-2026-clean` (`python scripts/run_eval_live.py --set v3`) before citing any number; (2) M2 slice-depth + 80th-threshold official eval; (3) M4 risk-budget only after those.

## Appendix — reproduce & files

- Tests: `python -m pytest tests -q` (52 passed).
- Evals: `python scripts/run_eval_live.py --set v1|v5|v3` (frozen `app/eval/gates.py`); probe: `python scripts/probe_devil_reachability.py`; diagnostics: `scripts/diagnose_exhaustion_thresholds.py`, `diagnose_history_window.py`.
- Reports: `data/v5_report_20260919.md`, `data/v5_1_report_20260920T092850Z.md` (+ interim), `data/m3_report_20260920T164933Z.md`, `data/eval_report_*.json` (7), `data/delivery_features.csv`, `data/sessions.log`, `data/quantplus.db`.
- Contract: `contract/schemas.json`, `frontend-client/client.ts` (auto-generated, do not hand-edit).
