# Wave 2 — Automated Quant Research Lab (report)

**Date:** 2026-11-12 · **Repo:** `D:\Quant-Plus` (dev) / `D:\QP\agent-service` (production sync) · **Plane:** research (paper-only, read-only, capital-sterile)
**Scope:** blueprint §7 + master prompt W2 — typed contracts, headless runner tools, adversarial challenge battery, holdout sealing, preregistered experiments, bounded sweep, honest artifacts.

---

## 1. Verdict (wave-level)

**PARTIAL — engineering delivered and verified; real-data economics honestly DATA_BLOCKED.**

Every W2 exit-gate engineering item works and is tested (§6). The two preregistered hypotheses were run end-to-end on the real 1.68 GB warehouse and came back **DATA_BLOCKED by rule** — the honest outcome given 31 unverified corporate-action windows and snapshot-floor membership spells. Nothing was promoted; W2 never promotes by design. One deliberate leak was caught by the challenger battery; one noise control was rejected. Deterministic identity is proven across independent full runs (§4.3).

## 2. What was built

`backend-extension/quantplus_intelligence/research_v3/lab/` (stdlib-only, no runtime-app imports — separate research plane per W1 precedent; reuses the exact W0 fee model and W1 warehouse):

| Module | Contents |
|---|---|
| `spec.py` | `StrategySpec`, `UniverseSpec`, `SignalSpec`, `ExecutionSpec`, `WindowSpec` (capital-sterile validation, spec fingerprint, preregistration hash, negative-control declaration); `BacktestResult` / `SweepResult` (plateau field) / `ChallengeReport` |
| `data.py` | `PitPanel` (alias-closure merge, `key_for()`, decision-gated bisect), momentum + near-52w-high signals with discontinuity/gap abstention, `list_data_coverage` |
| `runner.py` | `run_backtest` (monthly/quarterly rebalance, execution-to-execution fills, verified-action cash consistency, label censoring at fold boundaries, eligible pools in month rows), `run_sweep` (bounded, holdout-free, all variants recorded incl. failures), `run_cost_scenarios`, `compare_runs` (paired-config enforced) |
| `challenge.py` | 13-check adversarial battery: availability, membership, boundary continuity (within segments), purge/embargo, missing periods, benchmark provenance, nav reconciliation, cost scenarios, concentration, placebo (from month-row eligible pools), moving-block bootstrap (block=3), multiplicity, holdout integrity; preregistered verdict rules |
| `journal.py` | `ResearchJournal` — append-only hash-chained JSONL: seal (once/version), preregister, register_run/sweep/challenge, single reveal requiring prior seal (records runs evaluated before reveal), `status()`, `verify_chain()` with tamper detection |
| `__init__.py` | full public API incl. `run_backtest`, `run_sweep`, `run_cost_scenarios`, `challenge_finding`, `compare_runs`, `list_data_coverage`, `research_journal_status` |

Orchestrator: `backend-extension/scripts/wave2_run_lab.py` — seal → preregister 5 specs → train_validation runs → bounded sweeps → challenge battery → single holdout reveal → holdout evaluation (H1/H2/EW only; controls excluded by rule) → paired comparisons → coverage → 8 immutable artifacts.

**Preregistered hypotheses (unchanged across all runs):**
- **H1 momentum**: cross-sectional 6-month (126-session) price momentum, top-10 equal weight, monthly rebalance at the executable open. Sector-relative variant pre-declared DATA_BLOCKED (no verified historical sector map).
- **H2 near-52w-high**: 252-session available-high proximity, top-10, monthly. Never a 65-bar proxy.
- Baseline equal-weight (top-50) as paired control; leak control (same-day-close ranking, `declared_negative_control=True`); noise control (seeded random, declared).

## 3. Real-data run (final clean run)

Command: `python scripts\wave2_run_lab.py` (from `backend-extension`) — exit 0, 94.3 s cold / ~90 s warm.

| Spec (train_validation) | status | labeled / abstained months | fills | challenge verdict |
|---|---|---|---|---|
| H1 momentum-126/0/10 | DATA_BLOCKED | 100 / 2 | 953 | DATA_BLOCKED (9 pass / 2 fail / 2 inc) |
| H2 near-52w 252/10 | DATA_BLOCKED | 94 / 8 | 905 | DATA_BLOCKED (9 / 2 / 2) |
| Baseline EW top-50 | DATA_BLOCKED | 100 / 2 | 3630 | DATA_BLOCKED (9 / 1 / 3) |
| Leak control | DATA_BLOCKED | 102 / 0 | — | **REJECTED — challenger caught it** |
| Noise control | DATA_BLOCKED | 102 / 0 | — | **REJECTED** (declared) |

Holdout (2024-06-21 → 2026-09-17), revealed **once** (journal seq 23; `runs_evaluated_before_reveal` = all 5 trainval result_ids; controls never evaluated on holdout):

| Spec | status | labeled / abstained | segment structure | whole-window gross |
|---|---|---|---|---|
| H1 | DATA_BLOCKED | 27 / 0 | 1 contiguous segment 2024-06 → 2026-08 | **−19.53%** |
| H2 | DATA_BLOCKED | 27 / 0 | contiguous | DATA_BLOCKED |
| EW | DATA_BLOCKED | 27 / 0 | contiguous | DATA_BLOCKED |

The holdout is structurally contiguous (starts after the 2024 H1 hole), so the whole-window NAV is sound there; train_validation is reported as segments (2015(11), 2016–2022, 2023(11)) with no chained NAV through holes — W1's +71.07% product is explicitly NOT treated as continuous by this wave's tooling.

### 3.1 Why DATA_BLOCKED (typed, rule-enforced)

- `benchmark_provenance` FAIL on **every** real run: raw unadjusted fills cannot support an economic comparison vs TRI (total-return basis) while 31 action windows are unverified. `excess_vs_tri_labeled_not_cash = DATA_BLOCKED_BENCHMARK_BASIS_MISMATCH`.
- Membership: train_validation 25 strict / 46 weak spells of 70 members; holdout 23 strict / 33 weak of 56 (snapshot-floor upper bounds; no row-level first-known timestamps exist in any source). Weak rows are disclosed per fill and block economics.
- Net P&L: fee schedule `nse-cm-delivery-2026-03-01` effective 2026-03-01 only → `cost_scenarios` typed INCONCLUSIVE everywhere in train_validation (honest abstention, no synthesized fees).
- Placebo (eligible-pool matched random portfolios, n=50 draws, threshold 90%): H1 beats only **8%** (strategy gross product −0.026 vs noise median +0.326), H2 **4%** (+0.065 vs +0.633), holdout H1 **8%** (−0.195 vs noise median −0.076). **No edge in gross terms in either phase** — momentum added nothing over matched noise or the equal-weight baseline (paired monthly excess −0.43%/mo H1 vs EW over 100 common months; −0.63%/mo H2 vs EW over 94; comparison vs the noise control is refused as not-paired, correctly).

### 3.2 Negative controls

- **Leak control caught by rule-based audit**: concrete violation — MARUTI ranking on 2015-06-01T00:15 IST reads a bar available 2015-06-02T00:15 IST (same-day-close family). Verdict REJECTED; verdict reason names the caught checks. Promotion impossible by construction.
- **Noise control**: REJECTED as a declared negative control; never evaluated on the holdout ("a leaked control on the holdout would only re-teach it").

### 3.3 Determinism and integrity

- `result_id` = sha256 of the canonical payload minus the result's `generated_at` and the embedded spec's registration instant (`created_at`/`preregistration_hash`) — **two independent full runs produced identical result_ids across all 8 runs** (registration instants differ; ids match).
- Journal: 29 hash-chained events (seals → prereg → 5 runs → 2 sweeps → 5 challenges → reveal → 3 holdout runs + challenges); `chain_intact_all: true`; reveal recorded after tuning, once.
- Sweep: 16 H1 cells {63,126,189,252}×{skip 0,21}×{top_k 10,20} + 4 H2 cells — **every variant recorded** (incl. per-cell statuses), 0 failures, holdout unreachable from sweeps. Best H1 cell (252/0/20, gross product 1.033) is **flagged as an isolated peak** (5-neighbour median 0.475) — not treated as robust.

## 4. Bugs found and fixed during execution (all before the final run)

1. **`wave2_run_lab.py` line 139 — syntax error**: multi-line f-string broken inside braces (Python 3.11 forbids; 3.12-only feature). Fixed by hoisting the comprehension.
2. **`warehouse.DEFAULT_DB` resolves one directory too high** in the dev repo (`<pkg>/../../../data/...` → repo root) and `connect()` silently created an empty 98 KB stub DB at `D:\Quant-Plus\data\research_v3\`. The orchestrator now uses the W1-style explicit path (`backend-extension\data\research_v3\warehouse.sqlite3`, guarded by an assert); the stub and the stale seal-only journal from failed runs were deleted. `warehouse.py` itself (W1 code) was not modified.
3. **Artifact merge key collision** in `_write_artifacts`: `{**results, **holdout_results}` dropped the 3 train_validation payloads (same spec_ids). Fixed with phase-suffixed keys (`spec@phase`), matching the manifest convention.
4. **`result_id` was not rerun-stable**: the canonical id included the embedded spec's `created_at`/`preregistration_hash` (the smoke test passed only because it reused one spec object). Fixed in `lab/runner.py` (registration-instant fields excluded; the spec's pinned core fingerprint stays in) + docstring/contract note updated + new regression test.

Failed starts were cleaned (stub DB, journals, artifacts) and the final artifact set comes from a clean, fully deterministic run; **no spec, grid, or threshold changed between attempts** — only the writer and id computation.

## 5. Data gaps carried into the report

- 2024-01-01 → 2024-06-20 official-bar gap (no session for ANY symbol; excluded by window construction, not silently bridged).
- 31 unverified corporate-action windows (24 symbols / 32 name-months) block EW-vs-TRI economics and would permanently block OOS_VALIDATED/SHADOW_CANDIDATE even after they resolve — historical economics can never rest on unverified actions.
- No verified historical sector map → sector-relative momentum remains DATA_BLOCKED.
- No row-level membership first-known timestamps → 79 weak spell disclosures (46 trainval + 33 holdout).
- 2026-09-18+ vendor-only bars: holdout window ends 2026-09-17.

## 6. Tests

| Suite | Result |
|---|---|
| `tests/test_research_v3_lab.py` (dev) — hermetic fixture battery incl. W1 boundary-exit semantics, leak/noise controls, placebo from eligible pools, seal/reveal/tamper, and the new cross-registration determinism test | **28 passed** (3.2 s) |
| Full dev suite | **543 passed** (24.1 s) = 515 prior + 28 lab |
| Production repo `D:\QP\agent-service` (lab synced; `warehouse.py`/`economics.py`/`labels.py` hash-identical to dev) | **64 passed** (36 W1 + 28 lab) |
| W1 regression suites (boundary-exit semantics preserved; `exit_ref="OPEN"` tests) | green in both repos (within the counts above) |

## 7. Artifacts (all in `reports/alpha_v3_1/`, sha256-verified via `wave2_artifacts_manifest.json`)

`wave2_research_journal.jsonl` (29 events, chain intact) · `wave2_preregistered_specs.json` (5 pinned specs + fingerprints + preregistration hashes) · `wave2_backtest_results.json` (8 immutable payloads) · `wave2_parameter_sweep.csv` (20 sweep rows) · `wave2_challenge_report.json` (8 challenge reports + 3 comparisons + plateau note + verdict rules) · `wave2_holdout_registry.json` (`chain_intact_all: true`) · `wave2_data_coverage.json` · `wave2_artifacts_manifest.json` (hashes verified ALL_OK).

Run evidence: `backend-extension/reports_w2_run_log.txt` (final run log), `reports_dev_suite_log.txt`.

## 8. W2 exit-gate scorecard → matrix

| Gate item | Status |
|---|---|
| ≥2 complete deterministic cost-inclusive experiments (engine + real runs) | **PARTIAL** — engine is cost-inclusive by design and deterministic (id-stable across independent runs); net-months only exist from 2026-03-01, so train_validation cost checks are typed INCONCLUSIVE (honest abstention, not a failure) |
| ≥1 bounded sweep, all variants recorded | **PASS** — 16 + 4 cells, 0 failures, plateau flagged, holdout structurally unreachable |
| Challenger catches a deliberate leak + noise controls | **PASS** — leak caught with a concrete availability violation; noise control rejected; both never evaluated on holdout |
| ≥1 DATA_BLOCKED example | **PASS** — all real-data economics runs DATA_BLOCKED by rule with typed reasons |
| Immutable artifacts | **PASS** — sha256 manifest verified; hash-chained journal; result ids stable across reruns |
| Promoted strategy | **NOT MET (by design)** — W2 never promotes; real verdicts are DATA_BLOCKED; placebo shows no gross edge |
| Overall W2 | **PARTIAL** |

## 9. W3 readiness

Engineering unblocked: the lab's runner/sweep/challenge/journal contracts are exactly what W3 quant models consume. Economics remain gated on ingesting a **verified corporate-actions source** (split/bonus/dividend with effective dates) and, ideally, a verified historical sector map — until then, W3 should build on the same typed-abstention discipline and must not promote anything on raw unadjusted economics.
