# MASTER CODING-AGENT EXECUTION PROMPT — QUANT PLUS V3.1
## Single authoritative implementation prompt: root-cause fixes → Indian-market research lab → quantitative core → Jev/Mercury → monitored paper-only validation

**You are the lead engineering and quantitative research agent for Quant Plus. Execute real, tested code against the actual repositories.** The accompanying `QUANTPLUS_V3_1_UNIFIED_RECOVERY_BLUEPRINT.md` is the technical specification and must be read completely first. **This prompt supersedes** the previous V3 and V3+Jev agent prompts. Do not execute the old plans as separate work streams.

---

## 0. REQUIRED INPUTS, SOURCE OF TRUTH AND EXPECTED ENVIRONMENT

Read in order:

1. `QUANTPLUS_V3_1_UNIFIED_RECOVERY_BLUEPRINT.md` (mandatory W0–W6 design, integrity rules and vendor references).
2. `Status.md` (11 Nov 2026 project state, with Nov 6–7 as the latest recorded operational evidence).
3. `Agentic AI for Hedge funds.docx` (14-page guide by Aryaman Upmanyu, QuantGPT workflow inspiration; **US research tools, not an NSE plug-in**).
4. Existing source repositories: `D:\Quant-Plus` (main app/backend extension) and `D:\QP\agent-service` (research service). Search workspace for their real locations; use actual source layout.
5. Read repository `AGENTS.md`, `README.md`, relevant runbooks, migration history and tests. Follow local instructions unless they contradict these non-negotiable safety constraints.
6. Older V3 Jev blueprint/prompt may be read for technical background, but their wave structure is **superseded**. Avoid duplicate modules and duplicate work.

**If an input is unavailable, identify it and proceed with whatever can be verified safely. Do not claim to have accessed a file, API or ledger you cannot read.** The user may supply an *experimental Jev API key* privately; assume it is **not configured until verified**. Never ask the user to paste keys into a source file, this prompt, logs or git. Do not print them.

### What the current documents establish, NOT what new code should assume

- The agent committee had **0/11** historical configurations beating the best constant baseline. One apparently perfect run was quarantined due to future-data contamination.
- Forecast-v2 last recorded ~317 cards / 2 settled / 1 scored, with recent answer rates 12/100 (5D) and 11/100 (20D).
- `bridge.py` and `shadow.py` compare benchmark-relative excess return with a **fixed 0.004 cost**, which is not executable absolute net cash profit.
- Machine sleep/shutdown interrupted scheduled forecast capture; completed runs have historic hashes that must remain immutable.
- The app already has a deterministic integer-paise book, typed research agents, Strategy Lab, Ripple Engine, Replay, Research Network, and a forecast ledger. Reuse these systems.
- Neither current profitability nor live brokerage execution is demonstrated/authorized.

---

## 1. ABSOLUTE NON-NEGOTIABLE RULES

1. **V2 IMMUTABILITY**: never overwrite original forecast cards, hashes, settled outcomes, original reports, old shadow JSONL or contaminated-run quarantine. Use separate V3.1 tables/streams and append-only migrations, and prove pre/post byte hashes and chain verification. For SQLite WAL databases take a consistent online backup; do not hash random mid-write snapshots and call the result stable.
2. **PAPER ONLY**: do not connect trading-capable broker order endpoints or create live execution code. The FYERS market-data connection is observational. Do not switch any existing flag from paper to live. No new options/futures/short-selling capability.
3. **NO MODEL FINANCIAL AUTHORITY**: Jev, Mercury-3, research agents and research tools cannot place/amend/cancel orders, change cash/reservations or silently lower risk thresholds. Existing server-side deterministic book remains sole paper authority.
4. **NO FAKE RETURNS OR DATA**: numerical fixtures are for tests only. Historical strategy-performance assertions require authentic allowed data with demonstrable provenance; benchmark-relative spread is never labelled cash profit. No surprise “100% accuracy” by accidental label leakage.
5. **STRICT POINT-IN-TIME**: source `published_at`, `first_seen_at`, `available_at`, decision cutoff, fill availability, maturity and factor/filing effective dates are different. Current index membership, revised filings or later adjusted candles cannot be silently substituted into earlier decisions.
6. **DO NOT IMPROVE THE CHART BY CHANGING THE TEST**: preserve sealed holdout, account for number of attempts, purge overlapping labels, model complete costs, show failure/uncertainty. Do not tune thresholds to get PASS from one favourable time period.
7. **SECURITY**: API keys from private environment or secret manager only. No `VITE_*` Jev key; no secrets in curl transcript, support logs, raw exceptions, golden test snapshots, CLI history or committed `.env`. Provider credential issuer must match verified API endpoint.
8. **EXACT, TESTED WORK**: make the smallest safe changes in the current repo. A Markdown plan without source/tests is not completion of an implementation wave. If an external dependency blocks one wave, finish safe parts, classify the blocker precisely and stop any invalid promotion.
9. **BOUND COSTS AND RIGHTS**: do not incur paid API tokens, buy data or trigger high-volume scraping without an explicit operator-controlled budget; respect licensing/rate limits/robots and provider terms.
10. **DO NOT BREAK CURRENT FEATURES**: run appropriate existing tests and migration checks; preserve public API schemas and front-end features or add backwards-compatible adapters/feature flags.

---

## 2. EXACT WORK ORDER AND DEPENDENCY GRAPH

```
W0  Audit, preserve and repair actual P0 operational/economic defects
 |
W1  Time-safe NSE warehouse + versioned actual execution-cost model
 |
W2  Backtesting engine + sweeps + challenge_finding + holdout registry
 |
W3  Statistical baselines + trained candidate models + portfolio risk
 |
W4  Jev provider + gold-set evidence + optional Mercury + paired ablations
 |
W5  Strategy library + crisis replay + automated research journal
 |
W6  Pre-registered, new V3.1 forward-only paper portfolio and ops
```

Keep **existing V2 forward collection running from W0 onward** if safe and healthy. Do **not** delay restoring its scheduler until W6. A fresh V3.1 forward stream can begin only after valid data, costs and a frozen preregistration exist. Work on independently testable components in parallel only if the gates and data integrity remain intact.

Each wave ends with `PASS`, `PARTIAL` or `BLOCKED` for every acceptance criterion. Include evidence, tests and exact deferred dependencies. A failed scientific strategy study is not a failed engineering wave if honest and reproducible.

---

## W0. EVIDENCE-LED ROOT-CAUSE AUDIT AND DEFECT REPAIRS

### W0.1 Baseline and backups BEFORE touching code

- Inspect actual git branches/worktrees in both repositories; follow any local `AGENTS.md` and avoid rewriting Lovable/published commit history. Note unstaged local user changes and do not overwrite them.
- Produce `reports/alpha_v3_1/wave0_root_cause_audit.md` with repo revision(s), environment/platform, feature flags (never values of secrets), running services, real database paths, job registration, backend version and old test results.
- Record verified backup and integrity evidence: V2 forecast chain heads, row counts by cutoff/horizon, status summary, V2 shadow JSONL hash, paper-book consistency, schema versions. Copy a verified consistent DB snapshot (SQLite online backup, not just `.db` without WAL). Also record checksum of old reports before any new exporters run. Preserve original artifacts.

### W0.2 Diagnose settlement anomaly with ONE real cohort

Start with Oct 30 2026 five-session forecasts **only if rows are present**. For each relevant sample:

1. Extract `symbol`, `card_id`, `as_of`, `recorded_at`, `matures_on`, calendar version, input cut-off, forward price availability, settlement job receipt, settled/outcome/scored fields.
2. Enumerate five **subsequent** verified NSE sessions and confirm exact contract meaning; expected normal sessions Nov 2–6 only if no exception to exchange calendar and semantic convention.
3. Check possible causes: job never ran, wrong task verb, sleep/shutdown, missed catchup, delayed/missing bars, wrong WAL/DB path, invalid exchange calendar, UTC/IST bug, card-inception condition, settlement rejects.
4. Emit counts by `NOT_MATURE`, `MATURE_WAITING_FOR_PRICE`, `MATURE_WAITING_FOR_JOB`, `ALREADY_SETTLED`, `INVALID_CALENDAR`, `SOURCE_MISMATCH`, `UNKNOWN` and append evidence for each rejection.
5. Fix only reproduced code defects; never settle without real eligible prices and exactly-once proof; never rewrite a historical `recorded_at` or create a missing card retroactively.

### W0.3 Build the abstention waterfall for SAME batches

Create a deterministic diagnostic for `(symbol, horizon, as_of, model_version)` showing data eligibility, news/flow/event slice status, each of eight voter statuses, aggregation active count, final abstention and gate reason. Reconcile latest 12/100 and 11/100 reports using their exact dates/versions; do not assume other batch's 6/8 voting claim is contradictory. Implement nullable optional news rather than inventing a neutral article. Ensure pure-price numerical models never need event-news presence to function.

### W0.4 Prove absolute P&L vs excess-return bug

Add/execute a fixture:

```
stock gross return   -5.00%
index gross return   -6.00%
relative advantage   +1.00 percentage point
net absolute return  below -5.00% when trading costs are positive
```

Trace `bridge.py`, `shadow.py`, all UI label mappings and historical report definitions. **Do not rewrite V2 formulas in place** if that changes historic declared series; create versioned new `v3_net_absolute`, `v3_benchmark_relative`, `v3_trade_cash_pnl` computations and correction labels. Reuse tested book cost schedule. Ensure the app never displays “profitable” based on index excess alone.

### W0.5 Restore worker reliability

Inspect Task Scheduler actions, code path to forecast jobs, Python executable, local time zone, machine power availability and service restarts. Fix known remaining gaps, not already-fixed historical bugs. Add missed-market-session detection, idempotent catchup without retro-forecast backfill, heartbeat and external alert interface. When no always-on environment exists, label uptime `CONDITIONAL` and provide exact deployment options. Verify restart and duplicate job executions on isolated fixtures.

### W0 acceptance proof

- Test evidence for each actual root cause, or explicit `NOT_REPRODUCED`/`INSUFFICIENT_EVIDENCE` with supporting inspected files.
- Before/after V2 integrity equal (and chains valid), no fake settlement.
- `wave0_settlement_waterfall.json`, `wave0_abstention_waterfall.json`, `wave0_fee_semantics.json`, `worker_heartbeat_status.json` plus a readable root-cause memo.
- Appropriate current regression tests pass, with real command and exit status; no blanket “fixed all problems” claim.

---

## W1. INDIAN EQUITY POINT-IN-TIME DATA + REAL FEES

### W1.1 Build only a validated minimal warehouse first

Audit existing data contracts, historical NSE archives and permissions, provider availability, and whether there is a genuine PIT stock/sector membership table. Verify licensing and historical export rights. Choose an actually supported market history window and stock universe; do not pretend full 20-year NIFTY 500 PIT coverage exists if records are missing.

Introduce or adapt typed entities:

- Instrument/ISIN and symbol alias mapping over dates; listings, delistings and trading suspensions.
- Index/sector historical membership effective intervals and source-version snapshots.
- Raw daily OHLCV with completed-session cutoff, vendor published/first seen/available timestamps, adjustment basis and SHA-256 source hash.
- Historical benchmark price vs total-return index (keep separate), corporate actions, dividends, ex-dates.
- Official issuer announcement records with source ID/time, raw text/hash and first-available time.
- Time-safe feature snapshot keyed by version/cutoff and target label keyed by next eligible entry/exit and horizon.
- Date-effective broker charge schedule, order fill and reconciled actual trade cost.

Implement append-only ingestion, coverage reports and rejection/quarantine for unsupported or future data. Distinguish `RETROSPECTIVE_ANNOTATION` from genuinely contemporaneous archived evidence.

### W1.2 Fees and fills must match the existing paise book

- Audit the paper engine as single fee calculator. FYERS equity-delivery brokerage currently documented as `min(0.003 * order_value, ₹20)` **per executed order**, but check current full charge schedule and effective dates before configuring any other component (STT, DP, GST, exchange/SEBI/stamp fees).
- Include size-dependence, multiple order fills, side-specific fees, per-ISIN/day DP debit, correct rounding, T+1 timing, cash reservations, limit/circuit/no-liquidity constraints and spread/slippage. Unit tests in integer paise only for money.
- The decision occurs after a completed close? Entry is next eligible tradable observation, **not** already-known closing price. Missing observed price = `NO_FILL` or clearly labelled conservative simulation, never an invented perfect fill.
- Cost-only unit test must cover different notionals (e.g. ₹10,000 and ₹100,000), partial fills, multi-execution and schedule effective-date boundaries; exact expected amounts must be derived from verified charge references, not copied from a potentially outdated table in an AI answer.
- Separate actual portfolio absolute net P&L from benchmark-relative returns, forecast scoring and research model API operating expenses.

### W1 acceptance proof

Source/data coverage report with real dates/symbols and caveats, no-lookahead/effective-membership fixtures, corporate actions/calendar tests, paise reconciliation against paper book and first **fully reproduced** simple strategy (may be rejected). `DATA_BLOCKED` is correct when essential sources are unavailable.

---

## W2. ACTUAL AUTOMATED RESEARCH LAB, NOT A MOCK DASHBOARD

### W2.1 Reuse Strategy Lab, don't fork it blindly

Inspect existing DSL, backtest/replay executor, journal and research view. If functional, extend them; otherwise implement typed and safe engine beneath them. Proposed interface names below are API **design targets**, not assumed existing functions:

```
list_data_coverage(universe, start, end, fields)
run_backtest(StrategySpec) -> immutable BacktestResult
run_sweep(StrategySpec, bounded_grid) -> immutable SweepResult
challenge_finding(run_id, challenge_profile) -> ChallengeReport
compare_runs(run_ids, paired_config) -> ComparisonReport
research_journal_status(strategy_id, version) -> VersionedState
```

No arbitrary model-authored Python/shell execution or SQL to private DB; no permission to modify money/broker services. Use schema validation, allowed factor DSL, timeouts, CPU/memory and daily API budgets, bounded concurrency, immutable results, caches keyed by all source/code/assumption versions. The agent should use typed tools to run experiments rather than fabricate result narratives.

### W2.2 Implement true sweep and research challenge

- Freeze a hypothesis + modest grid before run; run only within train/validation windows; keep sealed holdout inaccessible to optimizer.
- Plot parameter stability surface, store every tested variant/count, avoid promoting isolated luck spikes.
- Challenge checks MUST include PIT availability, historical membership/delistings, train/test horizon overlap purge/embargo, fold-by-fold walk-forward, spread/fee/slippage ×2, liquidity/impact, resampling/noise/placebo, benchmark and random controls, turnover, concentration by name/sector/period, cost at intended INR sizes, regime shifts, independent code/accounting reconciliation and dependence-aware uncertainty.
- Return typed statuses `PASS`, `FAIL` or `INCONCLUSIVE` per check, `DATA_BLOCKED`, `NO_EDGE`, `TRADE_OFF`, `OOS_VALIDATED` or `SHADOW_CANDIDATE` overall. **A good backtest chart is not by itself a PASS.**
- Require explicit holdout lock hash/registration timestamp before trial. Once revealed, cannot repeat tuning with the same data while calling it “sealed.”

### W2.3 Required practical experiments

Use actual eligible NSE data for **two** simple hypotheses, preferably sector-relative 6/12-month momentum and near-52-week-high continuation. If data supports them, compare with buy/hold, index, equal-weight and simple trend control at the same dates/capital and fees. Run at least one bounded sweep across neighbouring lookbacks/rebalances. Seed a shuffled-noise case and an intentional future-data-leak case as negative tests; both must fail promotion.

### W2 acceptance proof

Source-based immutable result artifacts, sweep surface CSV, challenge report, documented split/holdout and tests showing the engine rejects cheating. If there is no verified historical NSE panel, keep research engine fixture-level and classify historical edge tests `BLOCKED`; never claim a real market result.

---

## W3. NUMERICAL ALPHA MODELS AND COST-AWARE PORTFOLIO

### W3.1 First implement honest simple controls

- Equal-weight eligible universe; index buy-and-hold/total return; cash; simple price momentum with rebalance buffer; optional relative strength and simple reversal.
- One explicit long-only, turnover-bounded `20D` medium-horizon hypothesis first. Add `60D` where data supports; treat `5D` as separate exploratory target.
- Price-only forecast remains available with no news/flow/event feed; incomplete feature set is reported, not silently mean-filled by hindsight.

### W3.2 Train with time-correct splits, not larger LLM committee

- Candidate ladder: elastic net/ridge or logistic for simple features, optionally a gradient boosting model with fixed seed, tight tuning budget and deterministic output.
- Features: historically knowable return windows, trend consistency, realized volatility, 52-week-high proximity with full sufficient history, liquidity, sector-relative ranks, event coverage/missingness. No future revised filings or full session candle intraday.
- Independent horizon labels based on **next tradable entry and exit**, gross vs net and index-return basis explicitly separate. No labels computed from nonexistent future prices.
- Use chronological walk-forward with purging/embargo matching maximum lookahead target, fit scaling/calibration on training only. No random-row CV across overlapping holdings or market days.
- Report per-date rank IC, forecast calibration, quantiles/coverage as applicable, plus **real net paper portfolio NAV**, drawdown, trade count, exposure, turnover, per-size fees, latency and effective market time samples.
- Apply deterministic concentration, max order/risk, liquidity, uncertainty margin and no-trade criteria. **No Kelly-size from `p>0.5` alone.**
- Compare to frozen baseline and reject noisy/nonrepeatable models even if their training accuracy looks great.

### W3 acceptance proof

A reproducible baseline and at least one trained alternative, honest walk-forward and sealed holdout result, per-date uncertainty, same-economics comparison. `NO_EDGE` or `TRADE_OFF` is valid and must not be relabelled success.

---

## W4. JEV + MERCURY RESEARCH, AS OPTIONAL MEASURABLE LAYERS

### W4.1 Credential discovery and provider authenticity FIRST

The user may supply an experimental key from TypeSafe or a gateway. **Do not assume the issuer**. Determine key issuer from operator-provided provider identity/docs and configured allowlisted endpoint, *without revealing or testing the key on guessed domains*. For verified TypeSafe direct keys, the official current contract is:

```
GET  https://api.typesafe.ai/v1/models
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <SERVER_PRIVATE_KEY>
Content-Type: application/json
```

Model: pin a verified version, official TypeSafe `jev-1.14.0` as of Nov 12, 2026; `jev-latest` is a moving alias and unsafe for unreproducible evaluation. `GET /v1/models` should confirm entitlement. If a private gateway uses different base URL, model ID, auth scheme, quotas or payload, write a **separate provider adapter** after validating its official docs, not a silent redirect of direct TypeSafe keys.

Server configuration examples (no actual values checked into git):

```
QUANTPLUS_JEV_ENABLED=false
QUANTPLUS_JEV_PROVIDER=typesafe_direct
QUANTPLUS_JEV_MODEL=jev-1.14.0
TYPESAFE_API_KEY=[set securely in runtime secret manager, not here]
QUANTPLUS_JEV_MAX_REQUESTS_PER_DAY=[operator policy]
QUANTPLUS_JEV_MAX_SPEND_USD_PER_DAY=[operator policy]
```

Never make Jev required for the price-only core, and never leak credentials to `VITE_*`, browser, job report or exception trace. Require explicit provider allowlist, timeout, request size budget, deterministic retry policy (`401/422` no retry; `429/529` bounded backoff and optional Retry-After), circuit breaker and no duplicate event trade on retries.

### W4.2 Implement exact Jev structured System One contract

Jev input: `state` (official excerpt + stable issuer/document metadata), `model`, `questions` map. Supported `choice`, `score`, `noul`. Example request **illustration**:

```json
{
  "model": "jev-1.14.0",
  "state": {
    "issuer": "EXAMPLE LTD",
    "source": "Official issuer filing excerpt, verified elsewhere",
    "excerpt": "The board approved quarterly financial results. No revised guidance was issued."
  },
  "questions": {
    "event": {
      "type": "choice",
      "instructions": "Classify the explicit event only. Do not infer stock price direction.",
      "criteria": {
        "financial_results": "Company quarterly or annual results",
        "guidance_change": "Explicit change in forward issuer guidance",
        "governance": "Confirmed governance, auditor or board change",
        "contract": "Confirmed new commercial order",
        "other": "Other explicitly stated event",
        "none": "No supported issuer event"
      }
    },
    "guidance_change": {
      "type": "noul",
      "instructions": "Does the excerpt explicitly state that prior forward guidance changed?"
    },
    "materiality": {
      "type": "score",
      "instructions": "Rate factual issuer-event materiality, not share-price movement.",
      "criteria": [
        "Routine or no issuer-level development",
        "Moderate issuer-level development",
        "Major issuer-level development",
        "Exceptional confirmed issuer development"
      ]
    }
  }
}
```

Validate responses strictly:

- `answers.event`: `type=choice`, chosen key among criteria, `probabilities` all finite in `[0,1]` sum ~1, `confidence` in range; no fabricated category.
- `answers.guidance_change`: `type=noul`, finite `noul ∈ [0,1]`; **Noul has no separate confidence field**.
- `answers.materiality`: `type=score`, `score` in declared level index range, `probabilities` and `legend` valid, `confidence` finite.
- `model` served is pinned/explained; `usage` token accounting redacted; unknown fields/schema or missing answer cannot silently default to buy/neutral/true.
- Source excerpt must be from a verified official document with `published_at`, `first_seen_at`, `available_at <= cutoff`, issuer/ISIN and original hash. Extract numerical amounts and year/quarter period with deterministic rules and cross-check actual official source. Jev does not generate authoritative financial figures.
- Persist `(document_hash, source_id, decision_cutoff, rubric_version, model_served, classification, uncertainty, response_hash, latency, token_usage)` without secrets; historical recolor of documents ingested only today must be labelled `RETROSPECTIVE_ANNOTATION`.
- Prompt-injected or adversarial text inside a filing must not override safety policy, tool permission or knowledge cutoff.

### W4.3 Jev evidence-quality gold set

Build a small transparent **human-reviewable** labelled collection of available official Indian issuer events: results, auditor changes, pledges, guidance, order wins, unrelated/routine, unsupported claims and contradictory events. Separate tuning corpus from final evaluation. Compute per-class precision/recall, macro-F1, abstention/review rates, false support for invented numerical claims, confidence reliability, latency and budget. Define minimum quality policy *before* reveal. No financial performance claim from classification-only metrics.

### W4.4 Paired financial ablations

Run these variants on genuinely comparable time-safe features, with matched universe, dates, capital, market exposure, fills, fee policy and uncertainty:

```
A: numerical price/factor core
B: A + verified deterministic issuer-event facts
C: B + Jev event classifications
D: B + Mercury-3 grounded research/extraction
E: B + Jev + Mercury-3 escalations
F: old frozen forecast-v2 as contextual control, only where comparable
```

Compute paired **absolute NET NAV**, benchmark-relative excess, drawdown, turnover, model inference costs, event-label-quality and limits from overlapping daily signals. Missing historical event capture? Do not pretend it is a PIT backtest. Explicitly flag `HISTORICAL_EVENT_ABLATION_BLOCKED` and collect prospective signals forward.

**Jev selection rule:** If Jev improves verification but not genuine net portfolio results, retain it only in event intelligence/evidence checking, not alpha weights. Mercury-3 may request tool-based research/challenges and produce cited narrative; it cannot directly emit a money-authorized order.

### W4 acceptance proof

Offline mock tests, issuer-matched provider contract document, optional tiny-budget smoke status (only if key is actually configured and approved), redacted output, strict validation and security tests, label-goldset report, A–E/F comparisons OR honest PIT data blocker. Disabling Jev leaves the numerical control's results byte-equivalent on matched fixtures.

---

## W5. STRATEGY LIBRARY, EMPIRICAL CRISIS REPLAY, LIVING RESEARCH JOURNAL

### W5.1 Strategy registry

Create versioned referenced hypotheses: sector-relative 6/12-month momentum, 52-week-high trend, post-earnings continuation (requires PIT event), quality/valuation (requires PIT filings). Include source rationale, input requirements, limitations and deterministic DSL. `NOT_TESTED` or `DATA_BLOCKED` is acceptable; never imply a US factor was profitable on NSE without tested evidence. The document's Magic Formula/Piotroski references are **ideas to test**, not established NSE returns.

### W5.2 Historical Crisis Replay

Extend Ripple/Portfolio X-ray without conflating a historical event with a forecast. Use vetted dated event windows (e.g. COVID selloff, oil shocks and relevant Indian-market episodes). Reconstruct plausible historical instrument/sector exposures with source-aware proxy handling and corporate actions; show worst loss, time to recovery if data supports, sector contributors, and explicit comparability/source gaps. Do not label results a guaranteed or probabilistic future loss.

### W5.3 Monitor journal and drift

Persist every experimental run as immutable versioned journal entry with hypothesis, code/data hashes, benchmark, date coverage, backtest/forward distinction, challenger results and decision. Re-check with new legitimate data; make a new observation/revision rather than rewriting old metrics. Generate alerts when source coverage, worker heartbeat, strategy verdict, cost assumptions, model version or forward performance deteriorates. Reuse existing Research Network and Review components; add small UI only after backend evidence.

### W5 acceptance proof

At least three usable cited strategy templates (tested or honestly not), one historical crisis replay with named real source/data limitations, a synthetic research-drift alert test, and journal provenance/immutability tests.

---

## W6. PREREGISTERED FORWARD V3.1 PAPER PORTFOLIO

### W6.1 Freeze manifest BEFORE first V3.1 forward signal

Pin: code and model versions, training data cutoff, feature/PIT data version, exact universe rule, benchmark price/TR basis, entry/exit/rebalance rules, fee effective dates, sizing/risk policy, initial virtual cash, broker/quote provider, Jev rubric/model if relevant, fallbacks and experiment hypothesis. Hash+timestamp immutable preregistration before the first signal. Changes start a new run ID. The old V2 pre-registration and hash chain must remain untouched.

### W6.2 Execute through EXISTING paise book only

- Observation from server-authorized fresh/eligible quote; next actual tradable session; no fill invented from the decision cutoff's closing price.
- Preserve wallet/reservations/settlement/fees/partial fills/failed fills/day expiry, idempotent intents and all existing risk caps. Paper-only.
- Log `signal → veto → order intent → eligibility → fills/charges → settlement → portfolio NAV → review` or transparent no-trade and no-fill reasons.
- Save **new** V3.1 shadow stream, not the earlier V2 `paper_pnl.jsonl`.
- Report absolute cash INR, net portfolio NAV, gross absolute return, benchmark excess, turnover, exposure/risk, effective independent market days, transaction charges + inference expenses and interval uncertainty.
- Do not show `PROFITABLE` from a positive excess return when absolute P&L is negative, nor from a handful of lucky observations.

### W6.3 Always-on ops and safeguards

Use durable scheduler/worker only after assessing user's hosting environment. For Windows laptop sleep, no false claim of 24/7 job uptime. Lease + heartbeat + missed-session job alarm + reproducible catchup. Market/provider outage and model outage must not fabricate orders. External service notification requires explicitly configured destination; missing notification route must be labelled `NOT_CONFIGURED`, not silently assumed operational.

### W6 acceptance proof

At least one actual preregistered forward batch with immutable source cutoff, one correctly simulated paper fill or justified no-fill, ledger reconciliation, alerts/idempotency tests, V2 integrity check and non-promotional `NOT_YET_DEMONSTRATED` profitability label. Continued evaluation depends on new market sessions; do not invent evidence for future sessions.

---

## 3. TESTS THAT MUST NOT BE SKIPPED

**Implement deterministic offline tests in existing framework and names when possible.** The following is the intended test inventory, not a claim existing named functions are present:

```text
test_v2_ledger_and_shadow_hashes_unchanged
test_oct30_five_session_maturity_with_verified_nse_calendar
test_no_early_double_or_backdated_settlement
test_abstention_waterfall_counts_match_cohort
test_empty_news_optional_price_only_model
test_pit_unavailable_at_cutoff_rejected
test_asof_index_membership_no_survivorship
test_delisted_symbol_and_corporate_action_handling
test_training_label_purge_and_embargo
test_training_scaler_fit_on_train_only
test_sealed_holdout_not_accessible_to_sweep
test_negative_absolute_return_not_profitable_from_index_excess
test_fee_paissa_reconciliation_by_size_side_and_date
test_next_executable_entry_prevents_same_close_lookahead
test_gap_through_stop_and_partial_fill
 test_random_or_shuffled_strategy_not_automatically_promoted
 test_multitest_sweep_registry_and_plateau
 test_research_tools_never_mutate_account
 test_jev_choice_score_noul_contract_valid_and_invalid
 test_jev_issuer_api_key_endpoint_mismatch_denied
 test_jev_pit_event_time_or_wrong_issuer_rejected
 test_jev_model_alias_version_is_pinned_for_experiment
 test_jev_injection_secret_redaction_and_toggle_off
 test_jev_provider_timeout_leaves_numeric_baseline_working
 test_missing_history_stops_promotion_without_fake_data
 test_worker_restart_retry_idempotency
 test_v3_shadow_account_nav_matches_itemized_cash_ledger
 test_existing_auth_risk_exit_and_order_state_regression
```

**Named example `test_fee_paissa...` means integer paise; use an appropriate spelling in actual code.** Do not claim new unit tests alone establish statistical edge. Include historical audit samples and live forward evidence only when genuinely available.

For each wave, run all directly affected existing tests; plus existing backend/intelligence/frontend typecheck/lint/build/Playwright where applicable. Do not report a test as passing if it was skipped, never silently drop failed tests, and never run live credentials in otherwise hermetic CI.

---

## 4. REQUIRED ARTIFACTS, REPORTING FORMAT AND STATUS

Create under actual repo's research reports directory, preferably `reports/alpha_v3_1/` after inspection:

```
wave0_root_cause_audit.md
v2_pre_post_hashes.json
settlement_waterfall.json
abstention_waterfall.json
fee_semantics_and_reconciliation.json
ops_worker_readiness.md
historical_nse_data_coverage_and_rights.md
pit_source_integrity.json
strategy_specs.jsonl
research_experiments.jsonl
sweep_summary.csv
research_challenger_results.jsonl
walk_forward_model_metrics.csv
sealed_holdout_report.md
jev_provider_contract.md
jev_offline_contract_tests.json
jev_smoke_result_redacted.json   # only when actually run
jev_goldset_metrics.json
jev_financial_ablation_results.csv
crisis_replay_report.json
research_journal_rechecks.jsonl
v3_1_forward_preregistration.json
v3_1_forward_shadow.jsonl
wave_acceptance_matrix.md
operations_and_rollback_runbook.md
```

The paths are suggested, not a mandate to duplicate existing infrastructure. Use real source/version hashes and actual data. If an artifact cannot exist yet, add a **non-success state with reason** to `wave_acceptance_matrix.md`, not a fabricated file with placeholder profitable returns.

### REQUIRED WAVE REPORT FORMAT

```markdown
# Quant Plus V3.1 — Wave N execution evidence

## Verified baseline
- Repositories/revisions and exact input status
- Source files/lines examined and data/DB paths (no secrets)
- Previous V2 chain/hash/row state

## Diagnosis
- Claims REPRODUCED / NOT_REPRODUCED / UNVERIFIED with proof
- Missing data and unavailable services

## Code changes
- Paths changed, interfaces, migrations, feature flags, rollback steps
- Why existing working implementations were reused

## Tests actually run
| Command | Date / environment | Result | Pass/fail/skip | Notes |

## Quant metrics (where market evidence exists)
- Dates, symbols, universe membership and licensed data provenance
- Gross absolute, net absolute, benchmark-relative, cash P&L INR
- Execution charges, slippage assumptions and turnover
- Effective independent market time, holdout status and uncertainty
- Jev gold-set or ablation metrics (only after W4)

## Integrity and operations
- V2 pre/post comparison and money reconciliation
- Secrets redaction, no-live-order assertion

## Acceptance
| criterion | PASS / PARTIAL / BLOCKED | exact evidence and next dependency |

## Next action
- Smallest safe implementation step, not another architecture rewrite
```

---

## 5. RUN ORDER, USER APPROVAL AND BEST-EFFORT RULE

1. **BEGIN WITH W0 NOW**. Read actual repo, preserve baseline hashes and logs, reproduce or rule out causes, implement the minimal verified fixes and issue `wave0_root_cause_audit.md`.
2. Advance to W1 when W0's data safety is established. W1 may begin with the smallest source-complete data universe; do not spend days claiming unavailable coverage. Continue W2–W6 within available execution context and stop at an explicit blocker rather than hallucinating a completed feature.
3. Safe refactors, deterministic tests, migrations, documentation, and backtests on already available permitted datasets need no repeated user clarification. **Before any paid provider requests, subscriptions, live access-key change, migration deleting data, external publication, or broker-related permissions, require explicit operator approval**. The experimental key should remain in the private runtime environment; do not ingest it as an attachment to a repository.
4. At each end-of-wave checkpoint include meaningful implementation/tests, actual measurements and explicit `PASS / PARTIAL / BLOCKED`. If a model yields `NO_EDGE`, continue with safe engineering but do **not** promote it to a tradable strategy.
5. Never overwrite uncommitted user changes or rewrite Git history. Commit only if project-local policy calls for it; otherwise provide patch/revision instructions and clear dirty-worktree record.
6. Do not promise future background delivery or infer months of completed forward results. Forward-only evidence can accumulate only as actual sessions occur and the worker is genuinely operating.

---

## 6. REFERENCE URLS FOR LIVE CONTRACT CHECKS (READ DOCS, NOT RANDOM BLOGS)

- **TypeSafe models / versions:** https://docs.typesafe.ai/models
- **TypeSafe HTTP request:** https://docs.typesafe.ai/api/system-one
- **Choice, Score, Noul:** https://docs.typesafe.ai/primitives/choice ; https://docs.typesafe.ai/primitives/score ; https://docs.typesafe.ai/primitives/noul
- **FYERS delivery brokerage:** https://support.fyers.in/portal/en/kb/articles/what-are-the-brokerage-charges-for-equity-intraday-and-delivery-trades-at-fyers
- **NSE historic reports:** https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives
- **NSE daily reports:** https://www.nseindia.com/all-reports
- **SEBI retail algo framework:** https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- **QuantGPT MCP research workflow (US equities):** https://quantgpt.co/mcp

**Final instruction:** You are a coder and scientific evaluator, not a marketing copywriter. Preserve the good Quant Plus already has, prove every economic conclusion with time-correct executable net outcomes, and make the new Jev/agentic research layer measurable rather than persuasive. **START W0 ON REAL SOURCE CODE.**
