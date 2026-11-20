# QuantPlus Agentic OS — Full Agent Report (till 2026-10-10)

**Date:** 2026-10-10 · **Repo:** `agent-service` · **HEAD:** (see git log) · **Suite:** 320/320 green
**Constitution:** `app/governance/constitution.py` v1 (R1–R15 enforced) · Docs: `docs/QUANTPLUS_CONSTITUTION.md`
**Models:** analysts `deepseek-v4-pro-0813` · deciders `claude-sonnet-5` (CodeCraft gateway)
**Prompt:** `PROMPT_VERSION=m12` · **Research policy:** `DIRECTION_POLICY=llm` (research/explainability only — NOT the money path)
**Eval gates:** frozen 2026-09-18, never re-tuned (`app/eval/gates.py`)

This file consolidates `MODEL_REPORT.md`, `AGENT_REPORT.md`, `D:\QP\PROGRESS.md`,
`data/ship_money_path_20261010.md`, all eval/paper/forward artifacts on disk, code state,
and failure analysis. Numbers are quoted as-is from artifacts; caveats travel with them.

---

## 1. Architecture: two paths, one boundary

```
MONEY (deterministic, zero LLM)          RESEARCH (full LLM, zero capital authority)
scripts/paper_trade_10L.py               POST /api/v1/sessions -> run_session()
  replays frozen run_core_v4               5 analysts (luna) -> debate (luna)
  + veto_fraction filter                   -> manager (sonnet) -> devil (sonnet)
  integer-share ledger                     -> trader -> 3x risk -> PM (sonnet + code guardrails)
  shadow cross-check vs run_core_v4 <1e-9
                    \                              /
                     llm_overlay_size() — SOLE composition point
                     LLM may veto / resize DOWN only, never direct, never upsize
                     (app/core/overlay.py, tests/test_money_path_boundary.py 22 tests)
```

The single-name LLM pipeline has **no demonstrated directional edge** (14 FAILs + certified
N=477 null), and deterministic trend-direction failed its out-of-sample read too (H1, 0.111).
The only audited positive is the deterministic core. So per prereg H1 decision rule
("FAIL → stop iterating on direction"): **code owns money, statistics own death, LLM owns
ideas that must survive falsification.**

---

## 2. Money path record (deterministic)

### 2.1 Cores

| Core | CAGR (after costs) | Sharpe | MaxDD | Note |
|---|---|---|---|---|
| v2 | +6.15% | 0.698 | 16.35% | frozen baseline, `GROSS_CAP=1.00`, `ROUNDTRIP=0.21%` |
| v3 (shipped target) | +5.25% | 0.705 | 12.46% | VIX filter, turnover + min-hold, vol target, caps |
| v4 narrow (2021–26) | +5.6% | — | 12.27% | v3 + baked veto, integer ledger |
| v4 broad (2021–26) | +18.5% | — | 10.8% | same rule, 391-name universe |

### 2.2 Paper ledgers (treated as-if-real: integer shares, cash drag, 0.105%/side)

₹10L (2021-01-01 → 2026-10-01):
| Book | Final | Profit | Costs | Trades | End state |
|---|---|---|---|---|---|
| Narrow (36 names) | ₹13,59,181 | +35.9% | ₹44,008 | 3,038 | 100% cash (trend off); 2022 −₹59.5k |
| Broad (391 names) | ₹25,99,423 | +159.9% | ₹90,330 | 7,906 | 23 holdings + ₹21L cash; every year green |

₹50L (same window, generated 2026-10-10):
| Book | Final | Profit | CAGR | MaxDD | Costs | Trades |
|---|---|---|---|---|---|---|
| Broad | ₹1,33,49,766 | +₹83.5L (+167.0%) | 19.04% | 10.89% | ₹4,60,859 | 9,595 |
| Narrow | ₹68,19,573 | +₹18.2L (+36.39%) | 5.66% | 12.44% | ₹2,22,535 | 4,092 |

Audit gems (per-rebalance decision records, cost-identity checked): FACT entered at
inception (₹125.78); 11 blowoff names vetoed day one; 122 names stress-blocked in one
Feb-2022 rebalance; 607 veto + 3,391 stress blocks (broad).

### 2.3 Honest environment (Day 1)
Segment costs (0.105/0.20/1.50% per side), circuit-lock model, 2026–27 RBI/Budget calendar
with gross-halving, token-spend deduction. Narrow ₹10L: inference spend **₹1,56,465
(43% of paper profit)**; net-of-cognition +₹2,06,140 vs +₹3,62,605 gross.

### 2.4 Blind test, unseen 2015–2020 (COVID + demonetisation + 2018–19 bear)
Narrow CAGR **+12.29%**, Sharpe 1.508, MaxDD 11.2% ✅ · Broad CAGR **+16.80%**, Sharpe 1.508,
MaxDD 24.4%, exposure 53.9% ✅ · 2020 +31%/+40.5% (trend sat out the fall, re-entered recovery).

### 2.5 Verification verdict (guilty-until-proven-innocent audit, 5 parts)
`data/paper_10L_verification_report_20261006T164227Z.md` — **NOT VALID AS STATED /
REQUIRES NEW OUT-OF-SAMPLE TEST**: 4 same-window iterations; confirmed survivorship bias
(broad **−4.8pp/yr**, 18.68%→13.87% under PIT membership); 2022 carried by 5 names
(FACT 68% of net, top-5 ≈147%); ~95% of broad return ≈ half-beta. Blind 2015–2020 PASS
upgrades v4 to "survived an unseen bear regime," not to "deployed."

---

## 3. LLM direction record (research path — negative throughout)

Gates: `n_decisive≥8`, `accuracy≥0.55`, `no-edge hold≥0.40`, `trade∈[0.20,0.90]`,
calibration directional, plus honest anchor `beats_best_constant=True`.

### 3.1 Official evals (frozen gates, one-shot each)

| # | Report | Prompt/set | n_dec | acc | hold | trade | PnL | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | `eval_report_20260918T165134Z` | pre-v5 / orig-24 | 12 | 0.333 | 0.583 | 0.625 | −0.0046 | FAIL |
| 2 | `eval_report_20260919T133151Z` | v4 / orig-24 | 12 | 0.333 | 0.667 | 0.458 | +0.0047 | FAIL |
| 3 | `eval_report_20260919T160958Z` | v5 / new-24 | 13 | 0.385 | 0.182 | 0.875 | −0.0047 | FAIL |
| 4 | `eval_report_20260920T074259Z` | v5.1 / orig-24 | 12 | 0.500 | 0.083 | 0.958✗ | −0.0063 | FAIL |
| 5 | `eval_report_20260920T092702Z` | v5.1 / new-24 | 13 | 0.385 | 0.091 | 0.917✗ | −0.0062 | FAIL |
| 6 | `eval_report_20260920T113129Z` | m3 / new-24 | 13 | 0.231 | 0.182 | 0.750 | −0.0104 | FAIL |
| 7 | `eval_report_20260920T164633Z` | m3 / orig-24 | 12 | 0.333 | 0.250 | 0.750 | −0.0032 | FAIL |
| 8 | `eval_report_20261005T091856Z` | m3 / v3rd-2026 | 17 | 0.176 | 0.429 | 0.625 | −0.0119 | FAIL |
| 9 | `eval_report_20261005T174643Z` | m3 / v3rd-2026 | 13 | 0.077 | 0.727 | 0.292 | −0.0037 | FAIL |
| 10 | `eval_report_20261006T062859Z` | m3 / v3rd-2026 | 17 | 0.059 | 0.857 | 0.250 | −0.0094 | FAIL |
| 11 | `eval_report_20261006T082257Z` | m3 / v3rd-2026 | 17 | 0.176 | 0.571 | 0.583 | −0.0092 | FAIL |
| 12 | `eval_report_retry_20261006T160307Z` | **m10 retry** / v3rd | 17 | **0.118** | 0.571 | 0.292 | +0.0017 | FAIL (reliably-wrong p=0.002) |
| 13 | `eval_report_deviloff_20261009` | devil-off ablation | 12 | 0.000 | 1.000 | 0.000✗ | 0.0 | FAIL (holds everything) |
| 14 | v6-2026h2-unburned (m11) | **partial 14/24, halted** — no verdict JSON (labels: 4 OK / 10 MISS so far) |
| 15 | v7-2026h2-unburned (m12) | **partial 10/24, halted** — no verdict JSON (labels: 4 OK / 6 MISS so far) |

Every completed run: `beats_best_constant=False`. At n≈12–17, 2 flips swing the headline —
single-run accuracy is noise-dominated; the constant verdict across 13 reads is the signal.

### 3.2 LLM paper arm (`data/llm_direction_arm.json`, ₹50L per arm, zero new tokens)
LLM direction compounded per eval: **−0.33% to −1.18%** (−₹16k to −₹59k), underperforming
hold (₹0) in 6/7 and always-long in 5/7. Doing nothing beats the LLM.

### 3.3 Deterministic trend direction (H1, `DIRECTION_POLICY=trend`)
Accuracy **0.111** vs best constant 0.556 → FAIL on fresh blind set. Beta/drift, not skill.
Both direction sources fail — hence the veto-only money contract (§1).

### 3.4 Independent null (`D:\Model` investigation, wired Steps 1–4)
Old-ML audit certifies the null at **N=477** (PBO/DSR, 11 pre-reg, 10 FAIL + 1 vol-skill PASS).
Upgrades our null from "small-n fails" to independently certified. Wired: PIT membership
(`pit_universe.py`), delivery parquet canonical + VIX swap BLOCKED (62.5%/87.5% < 99% rule),
TRI benchmarks (NIFTY50 TRI 10.54% 2021–26 — below hand-rolled benches, flattery quantified),
G1–G5 gates + calibration SIZING-ONLY scoping. Rejected: trained direction models + prob
`.npy` (null-laundering), labels/148-col features (future columns), HMM regimes.

### 3.5 Root causes (measured, §5 of AGENT_REPORT)
1. Manager almost never holds; Devil almost never breaks (72/72 HEALTHY live; BROKEN only in canary) — no brake on bad trades.
2. Exhaustion gauge invisible in production (60-bar slice → 8% fallback → 1/48 flags).
3. Momentum without regime context (M3 VIX gate restores trade-rate discipline, not direction).
4. Calibration inverted every run (fixed: `FIXED_BASE_SIZE=0.025`, code owns size).
5. Small-n noise + set reuse (v6/v7 fresh sets built; both partial).

---

## 4. Agentic OS engine (built Days 1–6, NEWW_PLAN)

| Piece | Files | State |
|---|---|---|
| Honest environment | `app/data/environment.py` | segment costs, circuit locks, event calendar, token deduction; 5 tests |
| Death engine | `app/evo/` (genome, store, judge, arena) | 8 founders, two-strike + starvation judge (60-decision infancy), IR-weighted allocation, seed-bank resurrection on exact fingerprint; synthetic-proven, zero LLM |
| Memory + calibration | `app/memory/` (layers, reflect, calibrate) | half-life decay, PIT settlement, dual reflection as veto context; isotonic + half-Kelly sizing in `[0,core]`, refuses training <50 forward labels |
| Foundry + positioning | `app/foundry/`, `app/data/positioning.py` | allowlisted kinds only (parse rejects rest), embargoed 60/20/rest + PBO-lite 8-block promotion (amended ↓2pp/±5pp), corpses logged; delivery + best-effort FII/PCR veto with abstention flags |
| Biting eval | `app/eval/dsr.py, perturb.py, friction.py` | DSR registry (12 trials; narrow DSR **1.0** vs 0.52 bar; broad PENDING), PC/CI/IDS suite, 13-cell friction matrix (5 modeled, 2 partial, 4 bounded, 2 N/A) |
| Production | `app/control.py, audit.py, api/v1.py` arena/kill/audit routes | kill-switch, 5-yr audit export, OpenAPI snapshot test, additive-only contract + TS client |
| Weekly ritual | `scripts/forward_week.py` + `tests/test_forward_week.py` | judge→allocate→foundry gate, forward-only, total on failure; hermetic tests |

---

## 5. Forward clock (live since 2026-10-10)

* `data/forward_clock_start_20261010.json` — 8 frozen founders (`F1 v4-as-shipped, F2 top30,
  F3 top70, F4 v3-control, F5 no-VIX, F6 strict-veto, F7 loose-veto, F8 low-gross`),
  equal-weight 0.125, 0 judgments. 2021–26 burned (12 DSR trials); no admission/kill on backtest.
* **Week 1** (`data/forward_week_01_2026-10-10.json`): 0 forward bars (Saturday; next slot Mon
  10-12) → 8× `clean / infancy: not judgeable`, allocation unchanged, 0 deaths;
  `direction_flip` probe rejected at parse; `veto_band_edge` candidate NOT promoted
  (test slice too small, logged). Live fingerprint `ELEVATED|DOWN|low` (VIX elevated, index
  downtrend, breadth 0.20). Research token memo 1,187,111 (not charged to variants).
* Cadence: `python scripts/forward_week.py` weekly after Friday close. Judgeable after 60
  forward decisions (~60 weeks).

---

## 6. Data inventory

* **Canonical:** delivery parquet (T+1, 0.005pp-consistent), yfinance research bars + direct
  `^INDIAVIX`, PIT NIFTY50/500 membership history, TRI benchmarks, NSE archive map
  (bhavcopy/delivery/bulk-block/FII-stats/announcements).
* **Partial:** FII/PCR positioning (best-effort, abstention flags), fundamentals (PIT-safe or
  `DATA_UNAVAILABLE`), event calendar (hardcoded 2026–27 RBI/Budget).
* **Rejected as direction signal:** delivery-as-alpha (failed 4 ways → exhaustion context only),
  trained direction models + prob files, 148-col features, HMM regimes, VIX swap (below 99% rule).
* **Needed (ordered):** forward-settled labels (only the clock produces them) → announcement
  feed w/ blackouts → bulk/block daily → reliable FII/PCR → PIT fundamentals → corporate-action PIT.

---

## 7. Config, contract, compliance

* Gateway: 5-key rotation, 1s pacing, Retry-After ≤300s, 5×(2–60s) retry, 120s timeout,
  402-quarantine, session 120k + day 3M(6M ops) caps, SQLite ledger. Deciders pinned to funded key.
* API: frozen v1 (sessions/theses/health/WS) + Day-6 additive arena/kill/audit routes; sid =
  `sha256(instrument|as_of|cfg|portfolio|mode)`; crash-resume checkpoints never re-bill.
* Compliance posture: research + paper only; AngelOne read-only stub (`NotConfigured`);
  weekly rebalance far below SEBI 10 orders/sec algo threshold; black-box-algo research artifacts
  map to RA requirement; **real money deferred** (live adapter + RA-license path gated).
* Research context adopted: Profit Mirage (tool-users resilient; code-owns-money validated),
  Alpha Illusion P1–P6 eval checklist, FinMem/FinAgent memory patterns in deterministic form.

---

## 8. Tests & commits

* Suite **212/212 green** (2026-10-10). Was 52 (09-22) → 171 (10-06) → 208 (freeze) → 212 (forward ritual).
* `57c0eda` NEW_PLAN build (leaks, scaffold, v3/v4, overlay, retry, paper + verification)
* `e234ce3` NEWW Days 1–5 (honest env, evo, memory/calibration, foundry/positioning, biting eval)
* `076055a` Day-6 freeze (money-path lock, audit/control, m12 evidence grounding, v6/v7 sets)
* `98a6df1` forward clock start · `f037877` Week-1 ritual
* Standing rule, unchanged: **LLM earns a money-path seat only by beating code out-of-sample
  under G1–G5 — never by argument.** No 2021–2026 backtest claim from here forward.

## 9. Pending

1. Weekly `forward_week.py` (next real signal Mon 2026-10-12 settlement).
2. Funded-window queue: Devil-off full ablation bill, broad DSR recompute; finish v6/v7 direction reads (~1M tokens, research-only).
3. Announcement-feed blackout pipeline on FORWARD data (next recommended experiment — exercises every new layer, touches no burned window).
4. v5-future: per-rebalance time-varying membership; Zerodha second adapter at live-execution time; RA-license path if real money ever considered.

## 10. Architecture migration (2026-10-10): prediction system → research OS

Full record: `data/migration_report_20261010.md`. Summary of what changed:

* **Governance:** R1–R15 machine-readable (`app/governance/constitution.py`); `FinalDecision`
  is RESEARCH_ONLY by type (fails closed); 9 authority flags, all safe defaults;
  `LLM_OVERLAY_ENABLED=false`; burned-dataset registry (only `forward-from-2026-10-10` promotes).
* **Research org:** 7 roles (5 specialists + director + falsifier) with output-contract +
  directive-scan validation; legacy analysts/manager/devil preserved byte-identical for archival evals.
* **Hypothesis→code:** strict schema (rejects BUY/SELL/weights/leverage/orders) + constrained
  Strategy DSL (17 ops, WEIGHT≤1 by construction, stable fingerprints, foundry bridge).
* **Memory:** hypotheses/experiments/corpses/lineage with dedup, DEAD_MATCH confrontation,
  reopen-only-on-new-evidence, MATCHED-PRIOR-CORPSE retrieval, evidence records + manifests.
* **Evaluation:** incremental-alpha, concentration, regimes, stability, LOO, placebo,
  benchmarks, data-quality + failure-first candidate report (weaknesses before performance).
* **Evolution:** GATESET_V1 (documented kill-favoring bars), strategy pool, genesis champion
  (v4 core, live), challengers, deterministic promote/retire.
* **Loop:** `app/research/orchestrator.py` (no LLM inside; injected propose_fn) + 7 additive
  research API endpoints + `scripts/reproduce_experiment.py`.
* **Events:** NSE/BSE ingest → normalize → keyword rules → opt-in LLM extraction behind a
  schema gate (identity smuggling rejected) → deterministic blackout engine.
* **Ablation verdict (§23):** C (core+LLM overlay) vs A (core) on 360 cached decisions =
  **−₹88.8k before inference costs → OFF** (66 vetoes + 119 resizes engaged, destroyed value).
  Config unchanged. Full Devil-off bill still queued.
* **Tests:** 212 → 269 green, zero regressions; every migration phase hermetic-tested.

## 11. Next phase: PIT-correct evidence (2026-10-10) — post-migration forward work

Full record: `data/next_phase_report_20261010.md` (A–J). Pre-migration §§1–9 and
migration §10 above are unchanged; nothing rewritten, no claim strengthened.

* **P0 PIT membership** (`app/data/pit_membership.py`): per-rebalance `membership_at`
  snapshots (hash/version/coverage/status); UNKNOWN freezes, ineligible names exit;
  integrated into `run_core_v4` + paper ledger (default-off, legacy byte-identical).
  Audit: 300 weekly rebalances 2021–2026, 0 violations, 0 unknowns. Correctness rerun
  on live panel: static 6.52% → PIT 5.95% (−0.57pp bias removed, thresholds untouched).
* **P1 immutable ingestion** (`app/events/store.py`, `textnorm.py`): append-only raw/
  normalized/versioned-classification store, duplicate+amendment links, §17 manifests,
  explicit failure log; scripts `ingest_announcements.py`, `audit_event_store.py`
  (production store honestly empty: 0 rows, 0 mismatches).
* **P2 extraction + blackout**: `EVENT_TAXONOMY_V1`, abstention triage, `Extraction`
  model (identity smuggling rejected), `BlackoutRule` + frozen `BLACKOUT_FAMILY_V1`
  B0–B3 (artifact byte-matched to code); shrink-only boundaries tested (§71–72).
* **P3 forward experiment**: manifest `data/event_blackout_v1_manifest.json` frozen
  before outcomes; harness compares A vs B1–B3 with per-bar PIT eligibility (§§42–45
  factual metrics, no invented notionals); verdict **EVENT_FORWARD_INFANCY**
  (0 announcements, 0 forward bars); memory row EXP-00001; §96 report generated.
* **P4 evidence classes**: `RISK_GATESET_V1`/`EXEC_GATESET_V1`/`DATAQUALITY_GATESET_V1`
  + auto-dispatch in `promote()`; risk passes on tail wins despite lower CAGR.
* **P5 broad DSR**: persistent trial ledger (18 seeded, append-only) +
  `scripts/recompute_broad_dsr.py` → Sharpe 1.526, DSR **1.0** over 13 trials
  (`data/broad_dsr_20261010.json`, §55 separate-label verdict).
* **P6 calibration**: priors locked at proposal time, Brier/bins/value-metrics,
  INSUFFICIENT (n=0) on production; capital-path isolation tested.
* **P7 registry + corporate actions + API**: one-way burn-state registry with
  promotion-access refusals; corp-action schema (all UNKNOWN until verified);
  expanded manifests; +6 research audit endpoints.
* **Tests:** 269 → 320 green, zero regressions; burned window never optimized.

## 12. Data acquisition layer (2026-10-10) — post-migration evidence work

Full record: `data/data_acquisition_report_20261010.md` (A–L). Pre-migration §§1–9,
migration §10, and next-phase §11 above are unchanged; nothing rewritten, no
strategy-performance claim added or strengthened.

* **Framework** (`app/data_acquisition/`): FetchStatus contract, bounded HTTP
  (timeouts/retries/Retry-After/backoff/pacing), raw-first atomic store with sidecars,
  content addressing (first-seen never backdated), manifests, quality reports, error
  log, source health, backfill checkpoints, acquisition ledger
  (LIVE/BACKFILL/MANUAL_IMPORT), scheduler windows + cron/schtasks instructions.
* **Collectors**: NSE/BSE announcements (ISIN cross-links, allowlisted attachments),
  NSE/BSE corporate actions (filing linkage, PIT confidence, factor-only PIT sync),
  equity EOD + delivery (§87 flags, adjusted prices UNAVAILABLE-marked), indices/VIX/TRI
  (per-row provenance), bulk/block (verbatim, no inference), FII/DII PROVISIONAL vs
  CDSL FINAL (graded comparison), F&O + participant OI/volume (separate tables),
  versioned PCR features (never scraped), XBRL filings (revision PIT, figures untouched).
* **Membership**: source classes end-to-end, press-release recon table, manual
  subscription importer (hash + validate + provenance).
* **Ops**: backfill engine (resume), daily updater, health monitor (today: all
  NOT_COLLECTED, shown not faked), snapshot freezer (SNAP-20261010: 11 datasets,
  0 artifacts), curated agent tools (provenance + PIT + caps), cost accounting split.
* **SQLite race (§64)**: reproduced with production error strings → thread-local +
  WAL + busy-timeout → stress 3×200 ops clean. Stable session code otherwise untouched.
* **Acceptance**: every dataset INGESTS hermetic (fixtures green) but production feeds
  are NOT_COLLECTED until scheduled — collection proven, live coverage pending.
  Forward experiment stays INFANCY (0 eligible events — correct).
* **Tests:** 320 → 362 green (42 new), zero regressions, zero deletions.

## 13. Live operations + correctness reissue (2026-10-10) — evidence phase begins

Full record: `data/live_operations_report_20261010.md` (A–K). Runbook:
`docs/OPERATIONS_RUNBOOK.md`. Prior §§1–12 unchanged; no performance claim added
or strengthened. Chronology preserved: original research → migration → PIT/data →
acquisition → live operations.

* **Scheduling**: job dispatcher (`run_job.py`) + calendar-aware post-close/
  settlement/intraday jobs + scheduler registry (cron/schtasks); missed runs
  surface as EXPECTED RUN MISSING. No OS jobs installed yet (operator step).
* **Health/alerts**: `quantplus_health.py` (SUSPICIOUS_ZERO for empty success);
  severity INFO/WARNING/CRITICAL with console+file sinks, dedup windows, durable log.
* **Snapshots/backups**: daily immutable snapshots + validation; evidence backup +
  successful restore rehearsal (0 failures); backups gitignored by policy.
* **PIT reissue (CORRECTNESS_REISSUE)**: frozen v4, 4 books regenerated with
  per-rebalance PIT membership, zero retuning — 10L narrow +31.0% (was +35.9%),
  10L broad +114.1% (was +159.9%), 50L narrow +32.2% (was +36.39%), 50L broad
  +114.8% (was +167.0%). Canonical artifacts preserved; PIT files are canonical now.
* **Audits**: corp-action store empty (honest); membership strict ratio 0.342
  confirmed; v6/v7 + devil bill ARCHIVAL_RESEARCH (no tokens).
* **Rehearsal**: dry/replay/live-shadow green; fixtures hash-verified untouched.
* **Forward ops**: UNSETTLED-first records, maturity-gated exactly-once settlement,
  agents see matured rows only; arena refuses backtest-flagged judgments.
* **Freeze**: `LIVE_FORWARD_FREEZE_V1` verified MATCH; drift quarantines runs as
  NO_JUDGMENT; forks mint new lineage. Change classes documented.
* **Ritual**: 11-step weekly order + monthly operations-only audit (no parameter
  advice by construction). Dashboard `status.py` reports live numbers.
* **Tests:** 362 → 390 green (28 new), zero regressions, zero deletions.

*(End of report — total ~9 sections. Sources: code + `data/*.json|*.md|*.log` + `MODEL_REPORT.md` + `AGENT_REPORT.md` + `D:\QP\PROGRESS.md`. Anything not in those is not claimed.)*
