# Quant Plus V3.1 — Wave acceptance matrix

**Last updated:** 2026-11-14 (Wave 6 engineering handoff) · Source of truth: Wave 6 final coding-agent handoff + unified blueprint.

Every criterion carries **PASS / PARTIAL / BLOCKED** with exact evidence. A missing artifact is recorded here as a non-success state with reason — never fabricated.

---

## Wave 0 — Audit, preserve, repair (COMPLETE)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| W0.1 | Baseline: repos/revisions, env, flags, running services, DB paths, job registration, old tests recorded | **PASS** | `wave0_root_cause_audit.md` §Verified baseline — `D:\Quant-Plus`@`36c0c96` + `D:\QP\agent-service`@`2a8b9dc`, 465 baseline tests, scheduler jobs, WAL ledger path |
| W0.1 | Consistent DB snapshot + V2 chain/integrity hashes BEFORE changes | **PASS** | SQLite online backup `reports/alpha_v3_1/backups/forecast_ledger_w0_backup.sqlite3` (sha256 `f5b21ed7…6288ab`); chain valid, 608 cards, head `fc7cea45…5fc67`; `v2_pre_post_hashes.json` |
| W0.2 | Oct 30 5D cohort diagnosed with ONE real cohort, waterfall counts by status | **PASS** | `settlement_waterfall.json`: 23/23 h=5 cards ALREADY_SETTLED (settled by Nov 11 job); 23 h=20 NOT_MATURE (mature ≈ Nov 27); all 608 rows classified; no price invented, no `recorded_at` rewritten |
| W0.2 | 9 matured-today cards handled without manual backdating | **PASS** | 9 cards `as_of=2026-11-04 h=5` mature 2026-11-12; tonight's already-scheduled 16:15 settle job handles them (to be verified next session) |
| W0.3 | Abstention waterfall for same batches with per-voter reasons | **PASS** | `abstention_waterfall.json`: 76.5% abstained; root causes quantified — LLM gateway "model unavailable" ~465–468/607 cards; events slice empty 607/607; news empty 470; flows unavailable 254; min_votes=3 gate. Recent-100 answerable 14/100 both horizons (reconciled with Status.md's 12/11 via differing batch dates + 103 older `forecast-v1` cards) |
| W0.3 | Pure-price model does not require event/news presence | **VERIFIED (design point)** | classical voters (momentum, reversal) answer on price alone — proven by waterfall; nullable-news already correct (`news/service.py` no fabrication) |
| W0.4 | Absolute P&L vs excess-return bug reproduced | **PASS** | `bridge.py:59` (`mean(excess) − 0.004`), `shadow.py:189` (`excess − 0.004`) traced; fixture: +1.00pp relative vs **−₹5,217.30** cash (−5.1173%) on ₹1L |
| W0.4 | V2 formulas untouched; versioned V3 metrics added | **PASS** | `research_v3/economics.py`: `v3_benchmark_relative`, `v3_trade_cash_pnl`, `v3_net_absolute` with mandatory semantics labels; V2 series byte-identical |
| W0.4 | Fee engine matches paise book exactly | **PASS** | `research_v3/economics.py` mirrors `src/lib/paper-fees.ts` (round-half-away-from-zero, STT rupee/fill); bun parity 6/6 fixtures all-match; ₹10k BUY 1188/SELL 1038, ₹1L BUY 11874/SELL 10374 |
| W0.5 | Missed-session detection + heartbeat + catchup idempotency verified | **PASS** | `forecast/heartbeat.py` + `jobs.py` additive edits; 9 tests in `test_worker_reliability.py`; live `status` run |
| W0.5 | External alert route operational | **PARTIAL** | route implemented + tested; webhook **NOT_CONFIGURED** — operator must set `QP_ALERT_WEBHOOK_URL` (env only) |
| W0.5 | Honest uptime classification | **PASS (labelled)** | `CONDITIONAL` in `ops_worker_readiness.md` + status JSON; InteractiveToken/laptop sleep documented with deployment options A/B/C |
| W0 | No V2 mutation / no fake settlement / no history rewrite | **PASS** | production ledger opened read-only or via online-backup API only; chain re-verified; quarantine untouched |
| W0 | Regression tests pass | **PASS** | `python -m pytest tests/ -q` → **479 passed** (465 baseline + 14 new), `11.40s`, 2026-11-12 |

**Wave 0 verdict: PASS** (W0.5 alert destination PARTIAL — operator action, no code work outstanding).

Deferred, precisely:
- `QP_ALERT_WEBHOOK_URL` set by operator (env var) → closes W0.5 alert PARTIAL.
- Uptime upgrade requires option A/B/C decision in `ops_worker_readiness.md` §3.2.
- 9 cards maturing 2026-11-12 verified settled by next session's check (normal job, not agent work).

---

## Wave 1 — PIT data + real fees (COMPLETE 2026-11-12)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| W1.1 | Data-contract audit: existing NSE archives, yf cache, calendar, membership sources inventoried with real paths/limits | **PASS** | `historical_nse_data_coverage_and_rights.md` §1–3 — bhavcopy 5,232,265 rows / 2,777 sessions 2015-01-01→2026-09-17 / 4,675 symbols (sha `4df01085…`); membership 6,525 spells 2014→ (sha `75ebfac3…`, CC BY 4.0); TRI 5,385 rows 2005→ (sha `d92d1a97…`); yf_cache = `VENDOR_RECONSTRUCTION` fallback only; `MANUAL/nifty500_membership` files identified as pytest leftovers, not data |
| W1.1 | Typed warehouse entities (instrument master, membership, daily bars, corporate actions, benchmarks, events, features, labels, fee schedules) | **PASS** | `research_v3/warehouse.py` schema: instruments, daily_bars (exact paise), membership_spells, symbol_renames, benchmark_bars, corporate_actions, fee_schedules, feature_snapshots, target_labels; events deferred to W2 lab (blueprint §7 placement) |
| W1.1 | Append-only ingestion + coverage report + rejection/quarantine + RETROSPECTIVE vs contemporaneous labelling | **PASS** | `INSERT OR IGNORE` everywhere; idempotency proven live — re-ingest 2026-11-12: 5,232,265 rows, **all duplicates ignored**, hashes unchanged; unrepresentable prices rejected (`test_unrepresentable_price_rejected`); `coverage_report()` + MISSING_SPAN gap states; `RETROSPECTIVE` stamped on sources and carried on reports; renames block re-derived per run (repair recorded in `pit_source_integrity.json`) |
| W1.1 | No-lookahead fixture: unavailable-at-cutoff data rejected in joins | **PASS** | `test_pit_unavailable_at_cutoff_rejected` + `test_no_same_session_lookahead_even_at_close`; availability = session + 1 local day + 15 min IST on every bar; all joins `available_at <= decision` |
| W1.1 | Effective-membership fixture: as-of membership, no survivorship | **PASS** | `test_asof_index_membership_no_survivorship` + `test_joiner_not_backdated`; VERIFIED/PARTIAL/UNKNOWN knowability classes with attribution per row; PIT probe nifty50@2020-01-01 = 50 members (36 weak rows disclosed), panel 50/50 with bars after instrument-identity aliases |
| W1.1 | Corporate actions / calendar fixtures | **PARTIAL** | verified symbol changes mirror as factor-1 actions (22 from 25 dated renames; undated/placeholder renames fail closed — `test_undated_and_placeholder_renames_fail_closed`); calendar = derived observed-session calendar; **split/bonus/dividend history ABSENT** — no verified local source (`app/data/corporate_actions.py`: none), adjustment abstains UNKNOWN, never imputed; 31 contaminated name-months quantified in `wave1_first_strategy_reproduction.json` — open item for W2 |
| W1.2 | Fee schedule effective-date audit against current charge references | **PASS** | schedule `nse-cm-delivery-2026-03-01` effective 2026-03-01; FYERS `min(0.3%·value, ₹20)` verified W0; pre-effective windows gross-only `SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE` (`test_schedule_effective_date_boundary_fails_closed`, `test_labels_before_fee_effective_keep_gross_only`) |
| W1.2 | Fill semantics: next eligible tradable observation, NO_FILL when no observed price | **PASS** | `test_next_executable_entry_prevents_same_close_lookahead`; entry = next-session OPEN, never decision close; NO_FILL typed; conservative exit extension labelled; `exit_ref="OPEN"` rolling-portfolio convention (`test_open_exit_ref_rolls_execution_to_execution`) |
| W1.2 | Size/side/date fee reconciliation in integer paise | **PASS** | `test_fee_paissa_reconciliation_by_size_side_and_date` (₹10k BUY 1188 / ₹1L BUY 11874 paise), STT rupee-per-fill rounding (5,080,000 whole vs 2×2,540,000 halves → 5100 ≠ 5000), FYERS per-order cap (`test_multi_execution_charges_each_order`), partial fills (`test_partial_fill_size_dependence`) |
| W1 | First fully reproduced simple strategy (may be honestly rejected) | **PASS (with recorded caveat)** | `wave1_first_strategy_reproduction.{json,md}` + `scripts/wave1_first_strategy.py` (preregistered spec) — EW NIFTY50 monthly rebalance, as-of membership, execution-to-execution fills, 133/141 months labeled, breadth 96.6%; cumulative gross **+71.07%** vs official TRI **+215.46%**; excess labelled benchmark-relative, NOT cash; **TRI comparison not economically interpretable until actions ingest** (31 raw-price action windows disclosed, none excluded, no factor imputed); strict-membership variant −11.59% secondary |
| W1 | Coverage/rights report artifact | **PASS** | `historical_nse_data_coverage_and_rights.md` + `pit_source_integrity.json` (regenerated each ingest run; source hashes, gaps, renames disclosure, rights) |

**Wave 1 verdict: PASS** — with two disclosed data limitations carried forward as W2 entry conditions:
1. **2024-01-01→2024-06-20 official-bar gap** (`MISSING_SPAN`): any W2 label window crossing it must abstain or exclude those sessions; no verified source ingested (no purchase made).
2. **Corporate actions (split/bonus/dividend) unverified**: EW-vs-TRI economics not interpretable until a verified actions source is ingested; the abstain discipline held (UNKNOWN, no imputation), contamination quantified (31 windows).

Resolved from the entering constraints: real PIT membership history WAS located (CC BY 4.0 vendored dataset) — the `SURVIVOR_BIASED_RESEARCH_ONLY` clause no longer applies to as-of-membership research.

---

## Waves 2–6

| Wave | Status | Note |
|---|---|---|
| W2 Research Lab | **PARTIAL** (2026-11-12) | lab built + tested (`quantplus_intelligence/research_v3/lab/`, 28 hermetic tests; dev suite 543; production 64). Real runs: all economics DATA_BLOCKED by rule (31 unverified action windows, weak membership spells, TRI basis mismatch); leak control caught → REJECTED; noise control REJECTED; holdout sealed → single reveal → contiguous 2024-06→2026-08 segment (H1 gross −19.53%, no edge vs placebo 8th pct / EW); sweeps 16+4 cells all recorded; journal chain intact; artifact manifest sha256-verified; result ids stable across independent reruns. Evidence: `wave2_research_lab_report.md` |
| W3 Quant models | **PARTIAL_DATA_BLOCKED** (2026-11-13) | typed PIT feature/label pipeline + 6-family baseline ladder + purged walk-forward built and run on real data: 25,316 snapshots, 49,989 labels (47,852 admissible / 163 action-blocked / 1,974 NO_LABEL), 72 runs (18 combos × 4 expanding folds, embargo 10), **0 failures**; 30 hermetic tests green in both repos (dev full suite 573; production 594 passed / 5 pre-existing credential-dependent failures in user-modified files); challenger battery: 9 REJECTED (momentum negative at every horizon), 9 RESEARCH_DIAGNOSTIC (h20 cluster: logistic +0.051, ridge +0.046, hgb +0.037 day-clustered IC, ≥98.5th perm percentile; thinned-t only 1.6–1.8 over 26 days — suggestive, not significant), negative control at chance (Brier 0.2500); NET_ABSOLUTE + BENCHMARK_RELATIVE typed DATA_BLOCKED (fee schedule 2026-03-01; raw-fills vs TRI basis mismatch); NEW_SEALED_HOLDOUT_UNAVAILABLE → forward protocol preregistered; journal chain intact with two chained full-run registrations (rerun determinism); nothing promoted to TRADE. Evidence: `wave3_model_comparison.md`, `wave3_challenger_report.md`, `wave3_input_data_and_split_audit.md`, `wave3_economics_and_actions_blockers.md`, `wave3_forward_protocol.md`, `wave3_acceptance_report.md` |
| W4 Jev/Mercury | **PARTIAL_DATA_BLOCKED** (2026-11-14) | `events_ai` package built + offline-tested: typed PIT issuer-event evidence (schema `evidence/1`, semantic `event_id`/`classification_id` excluding capture metadata and wall clock), validated Jev SystemOne adapter (fail-closed: budget preflight, bounded 429/5xx retries, circuit breaker, NaN-rejecting parse, injection scan, host allowlist, secret scrubbing) and bounded Mercury-3 research dispatcher (frozen 4-tool allowlist over W2 lab functions, deterministic executors only, grounded-citation check, idempotency, 8 calls/session, default-disabled) — **78/78 tests** in both repos (dev full suite **651 passed** = 573+78; production **670 passed / 5 KNOWN_PREEXISTING / 1 FLAKY_LIVE_LLM** classified with zero W4 frames and passing in 2 earlier runs / **1 layout-aware skip** after a W4-introduced prod-only failure was found in run 1 and fixed). Issuer verified (ExperientialLabs org key via vendor docs + prod config); live smokes redacted ~$0: **Jev 1 call HTTP 200 `jev-latest` 810 ms 616/110 tok gateway cost 0.0** (answers contract-valid, no alpha claim), **Mercury 2 calls HTTP 200 `mercury-3`** (first `max_tokens=8` consumed by reasoning tokens → empty visible content, honestly documented; second `max_tokens=64` OK); chat-pasted key flagged **ROTATE** (never used anywhere: server key fingerprint differs; never echoed/logged/copied); `typesafe_direct` **NOT_TESTED** (no TypeSafe key exists). Goldset = 24 authored synthetic fixtures (`ENGINEERING_CHECK_SYNTHETIC`, labeler-authored pre-reveal, hand-computed metrics pinned: paired_n 19, baseline 9/19 vs scripted-model 15/19, guidance Brier 0.04875); real goldset **GOLDSET_HOLDOUT_UNAVAILABLE** + preregistered minimum-quality policy + forward capture protocol. Paired ablation: **Arm A `UNCHANGED`** (frozen W3 hashes recomputed exactly with events plane off: feature `634b3669…`, label `0053df3d…`, counts 49,989/47,852/163/1,974), **B–E `HISTORICAL_EVENT_ABLATION_BLOCKED`** (no contemporaneous historical event corpus — forward signals only), **F contextual-only**; `quantlab` never imports `events_ai` (AST-tested). Nothing promoted to TRADE. Evidence: `wave4_acceptance_report.md` + 10 further `wave4_*` artifacts |
| W5 Library/crisis/journal/event capture | **ENGINEERING PASS / EVIDENCE PARTIAL_DATA_BLOCKED / ECONOMICS DATA_BLOCKED** (2026-11-14) | 3 cited immutable strategy revisions (near-52-week-high and separate 6/12m momentum diagnostics compile to the frozen W2 DSL; PEAD is explicitly `DATA_BLOCKED_EVENT_CORPUS` + `NOT_IMPLEMENTED_SPEC_CONTRACT`; no profitable state); source-anchored India COVID replay over 2020-01-14→2020-03-23 local official bars is `HISTORICAL_RETROSPECTIVE`, raw `PRICE_ONLY`, 85% same-ISIN mapped / 15% unmatched, 48/48 sessions, supported-component change −36.35%, drawdown −37.16%, no full-portfolio or forecast claim; independent hash-chained W5 journal retains synthetic `RESEARCH_DIAGNOSTIC→REJECTED` conclusions and emits exactly one deduped unconfigured-delivery alert; default-disabled rights/PIT event capture foundation has **0 legally captured W5 rows / 0 real gold labels**, with retrospective/no-backdating/correction/injection fixtures; W3 feature `634b3669…`, label `0053df3d…`, counts 49,989/47,852/163/1,974 and W4 Arm A byte identity recomputed `UNCHANGED`, W2/W3 journal hashes/chains unchanged, no Jev/Mercury call. W5 tests 62/62 in each repo; dev full **713 passed**; service offline-safe full **732 passed / 5 known pre-existing failed / 2 skipped** (live-provider node deliberately skipped; W4 sixth flaky live failure still tracked, not called). Evidence: `wave5_acceptance_report.md`, `wave5_reproducibility_manifest.json` |
| W6 Forward shadow | **ENGINEERING PASS / FORWARD NOT STARTED / ECONOMICS DATA_BLOCKED** (2026-11-14) | Null/no-trade protocol sealed before any real decision; 0 genuine sessions/signals/fills; 57 hermetic Python tests + 6 existing-engine TypeScript adapter tests; fixture accounting/worker chaos only; `WORKER_NOT_DURABLE`, `WEBHOOK_NOT_CONFIGURED`; forward study remains open. |

---

## Artifact status (master prompt §4 list)

| Artifact | Status |
|---|---|
| `wave0_root_cause_audit.md` | ✅ written |
| `v2_pre_post_hashes.json` | ✅ written |
| `settlement_waterfall.json` | ✅ written |
| `abstention_waterfall.json` | ✅ written |
| `fee_semantics_and_reconciliation.json` | ✅ written |
| `wave0_fee_semantics.json` | ✅ written |
| `worker_heartbeat_status.json` | ✅ written |
| `ops_worker_readiness.md` | ✅ written (W0) |
| `wave_acceptance_matrix.md` | ✅ written (this file) |
| `historical_nse_data_coverage_and_rights.md` | ✅ written (W1) |
| `pit_source_integrity.json` | ✅ written (W1; regenerated per ingest run) |
| `wave1_first_strategy_reproduction.{json,md}` | ✅ written (W1; the "may be honestly rejected" exercise) |
| `wave2_research_lab_report.md` | ✅ written (W2) |
| `wave2_research_journal.jsonl` · `wave2_preregistered_specs.json` · `wave2_backtest_results.json` · `wave2_parameter_sweep.csv` · `wave2_challenge_report.json` · `wave2_holdout_registry.json` · `wave2_data_coverage.json` · `wave2_artifacts_manifest.json` | ✅ written (W2; sha256 manifest verified, journal chain intact) |
| `wave3_input_data_and_split_audit.md` · `wave3_model_comparison.{json,md}` · `wave3_challenger_report.md` · `wave3_economics_and_actions_blockers.md` · `wave3_forward_protocol.md` · `wave3_feature_label_contracts.json` · `wave3_research_journal.jsonl` · `wave3_journal_status.json` · `wave3_reproducibility_manifest.json` · `wave3_acceptance_report.md` | ✅ written (W3; manifest sha256-verified incl. md artifacts, journal chain intact) |
| `wave4_provider_contract_and_security.md` · `wave4_event_evidence_manifest.json` · `wave4_goldset_methodology.md` · `wave4_goldset_metrics.json` · `wave4_mercury_research_tools_audit.md` · `wave4_ablation_protocol.md` · `wave4_ablation_results.{json,md}` · `wave4_regression_and_prod_failures.md` · `wave4_acceptance_report.md` · `wave4_reproducibility_manifest.json` · `wave4_w3_control_reevaluation.json` | ✅ written (W4; manifest sha256-verified incl. code modules + fixture; control reevaluation verdict UNCHANGED; report hashes pin `generated_at` by design) |
| `wave5_preflight_and_source_rights.md` · `wave5_strategy_library_manifest.json` · `wave5_strategy_library_report.md` · `wave5_crisis_catalog.json` · `wave5_crisis_replay.{json,md}` · `wave5_research_monitor_log.jsonl` · `wave5_monitoring_and_alerts.md` · `wave5_forward_event_capture_protocol.md` · `wave5_event_capture_manifest.json` · `wave5_w4_and_w3_control_reevaluation.json` · `wave5_regression_and_prod_failures.md` · `wave5_acceptance_report.md` · `wave5_reproducibility_manifest.json` | ✅ written (W5; engineering pass, evidence/economics blocked as labelled; no forward event rows, provider call, trade authority or W6 start) |
| `wave6_*` mandatory evidence pack | ✅ engineering artifacts written; real forward/economic study remains open (0 genuine decisions/fills) |
| `strategy_specs.jsonl` … `operations_and_rollback_runbook.md` | ⏳ W4–W6 targets (recorded as pending, not fabricated) |
