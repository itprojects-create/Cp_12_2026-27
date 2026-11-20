# MASTER CODING-AGENT PROMPT — QUANT PLUS ACCURACY BREAKTHROUGH SPRINT

You are implementing **one additional, bounded, read-only experimental accuracy sprint** for Quant Plus V3.1 after Waves 0–6. This is *not* a new trading wave and does not override W6 economic gates. Your goal is to improve the ability to predict NSE stock UP/DOWN movements beyond trivial always-UP/majority baselines while rigorously documenting uncertainty. You must implement, run and test the pipeline in the actual checkout, not merely write a proposal.

## Inputs and repos

Read these *before changing anything*:
- `D:\Quant-Plus` (main development repo) and `D:\QP\agent-service` (research service repo).
- `reports/alpha_v3_1/college_accuracy/` especially `evaluation_spec.json`, `directional_accuracy_results.json`, `oof_predictions.jsonl`, and `reproducibility_manifest.json`.
- W3 model/feature/label contracts, W2 split and journal artifacts, W4 event evidence contracts, W6 acceptance and economic blocks.
- The attached `QUANTPLUS_V3_1_ACCURACY_BREAKTHROUGH_BLUEPRINT.md` (the sole specification for this sprint), and any `AGENTS.md` repository instructions.

Do not copy digest strings out of chat or blueprint into tests: read them from actual prior manifests, verify existing seals, and preserve old hashes unchanged. Derive the correct OPEN-to-OPEN label hash from the college artifact. Keep all user-modified tracked files and ignored data untouched. Do **not** commit, stage, push, deploy, contact brokers, request credentials, or call models unnecessarily.

## Non-negotiable established truths

- h20 Logistic OOF DEVELOPMENT: 57.56% raw accuracy, 50.53% balanced accuracy, approximately 95.6% predictions UP, majority/fixed UP 57.72%; paired Δ −0.16 pp (CI −0.97 to +1.07). Confusion matrix TN=107, FP=2037, FN=115, TP=2812 on the 5071 common sample.
- h5 Logistic 54.17% vs majority 54.01%, paired Δ +0.16 pp (CI −1.08 to +1.22).
- Existing 2022–2023 W3 OOF tiles, W2 revealed holdout, and training data are **not new independent test data**. Do not select a winner using 2022–2023 outcomes and then claim independent evidence on those same outcomes.
- No W6 genuine forward sessions; W6 `NO_ELIGIBLE_STRATEGY`. Academic read-only forecasts may be independently logged, but no trading authority follows.
- Corporate actions, historical membership and fees block economic evaluation. Raw OPEN-to-OPEN directional academic evaluation may run with explicit action-window quarantines and honest limitations.
- The key goal is *baseline-relative skill*, not simply crossing 50% because the historical UP class is common. A positive result not beating baseline must be reported as such.

## Execute in this exact order

### Step A0: Fingerprint and re-verify baseline

1. Run existing college verifier and scoped tests. Verify prior result IDs, seals, feature/label hashes and full confusion counts. Determine exact TRAIN_ONLY/DEVELOPMENT/REVEALED/FORWARD splits and exact point-in-time data timestamps.
2. Record preflight git status of both repos and the W6 paper ledger heads. Never modify them.
3. Create a *new* immutable preregistration (`accuracy_sprint/preregistration.json`) **before any new scoring**, recording the complete candidate list, fixed grids, primary metric, baselines, tie rules, stopped/out-of-scope conditions, planned data eligibility rules, maximum attempts and timing. Hash it and link to old baseline result.
4. If the task cannot run without changing old manifests, stop with a specific blocker; never overwrite W3/college evidence.

### Step A1: Fix the UP-bias root cause

Implement class-weighted and unweighted Logistic, regularized Ridge-derived sign classifier, class-balanced/shallow HGB, and a train-only calibrated threshold comparison. Record each model's predicted-UP share, DOWN recall, UP recall, confusion matrix, macro-F1, balanced accuracy, MCC, Brier and raw accuracy. Explicitly show tradeoffs. No resampling across time or held-out observations. Do not artificially rebalance the *evaluation* class distribution.

### Step A2: Implement a novel but small regime-aware two-head model

Head 1: estimate future broad-market OPEN-to-OPEN direction / return from only pre-cutoff index or genuine tradable proxy historical features.
Head 2: estimate stock-specific return or rank relative to the same point-in-time benchmark.
Combiner: small regularized/logistic calibrator, fitted strictly on inner-training out-of-fold predictions, to produce **P(stock absolute OPEN-to-OPEN return > 0)**. Do not assume independence or combine `P(market_UP)` and `P(stock_outperform)` with naive multiplication; these do not mathematically determine absolute direction.

Regime candidates: pre-cutoff index 20/60-day trend, realized-volatility percentile, market breadth and cross-sectional dispersion; always label regime **OBSERVED_CONTEXT**, not future state. No index basis/time alignment => typed DATA_BLOCKED for this model, not fabricated results. Compare a simpler regime-interaction Logistic before costly mixture-of-experts; only implement more complicated experts if a predeclared ablation justifies it.

### Step A3: PIT cross-sectional factor features

Within the **historically knowable** eligible universe, compute normalized ranks of lagged 5/20/60/126/252d momentum, short-term reversal, historical volatility, relative volume, distance to high, beta if a validated benchmark exists. Handle weak membership distinctly; if a verified sector PIT map does not exist, sector ranks are DATA_BLOCKED. Use no corporate action inferred from price shapes. Record feature-value time and source availability for each row; make a look-ahead adversarial test that deliberately injects one post-cutoff field and expects rejection.

### Step A4: Bounded nonlinear model comparison and selective decisions

Compare fixed, shallow HGB with the old baselines, and optionally one pinned local CPU-efficient boosted model if available; avoid heavy transformer training and hyperparameter fishing. Optional ensemble is allowed only if base predictions are genuinely inner-training OOF and model selection is predeclared. Test whether the added models yield novel information, not just a duplicated bias.

Build one train-only policy for coverage levels 100%, 75%, 50%, 25% and 10% only if sample supports it. Report selective accuracy AND abstention counts/coverage AND unconditional accuracy AND accuracy at matched-coverage baseline. Include performance by true class and volatility regime. Do not use the test set to choose a favourable confidence threshold.

### Step A5: Leakage challenge and exact result reporting

- Purge overlapping label intervals (use actual start/end instants) and enforce sequential train/validation/test chronology. A mere 10-session embargo does not necessarily clear h20 labels: use complete label-period overlap exclusion.
- Train-only preprocessing, rebalancing, calibration and thresholds.
- Baselines fixed UP, fixed DOWN, expanding training-majority and simple train-only market-conditioned rule; compare on identical common row sets and also report full eligible coverage.
- Paired accuracy differences vs majority with session-clustered bootstrap 95% CIs and appropriately sized time blocks; document effective independent temporal horizons. Fold/year/regime stability and permutation / label-shift negative controls.
- Freeze every attempt and hyperparameter configuration in the ledger. No hidden failures or re-running until a number looks good. If significant multiple-testing pressure arises, report full trial counts and caution, not unadjusted best-of-many significance.
- All **historical OOF** outputs from 2022–2023 must be marked `HISTORICAL_OOF_DEVELOPMENT` regardless of apparent improvement. W2 revealed holdout must remain unused for model promotion.
- If no genuinely unseen independent prospective matured observations exist, produce `INDEPENDENT_FORWARD_UNAVAILABLE` rather than inventing a seal. Seal a *future, read-only academic predictions stream* based on the chosen inner-training rule to evaluate real future h5/h20 observations later. Do not activate real W6 trades.

### Step A6: Deliver actual artifacts, regression proof and college-ready wording

Under `reports/alpha_v3_1/accuracy_sprint/`, create:

1. `preregistration.json` and sha256 seal; attempt registry with every candidate and test.
2. `baseline_reconciliation.json` and `feature_availability_audit.md`.
3. `model_ablation.{json,md}`; confusion tables and per-fold/per-year/per-regime metrics.
4. `accuracy_comparison.{json,md}` with point estimates, paired CIs, majority baseline, balanced accuracy, MCC, macro-F1, coverage, non-overlapping-period counts; metric scripts reproducible from prediction rows.
5. `confusion_matrices.png`, `risk_coverage.png`, `calibration.png`, `regime_ablation.png` **only** if grounded in actual results (or explicitly omit with reason).
6. `academic_forward_protocol.md` including model freeze, first-seen timestamps, post-seal horizons and maturity, forecast hash chain, read-only restrictions, and the scheduler's real durability state.
7. `college_results_section.md` with precise claim wording and all limitations; no unsupported '+60%', 'beating market', independent validation or profitable language.
8. `acceptance_report.md`, `test_runs.md`, `reproducibility_manifest.json`, verifier and two-repo sync report.

The final report must show one of these: (i) concrete developmental improvement relative to 57.72% / 54.01% together with limitations, (ii) a balanced-accuracy improvement that sacrifices raw accuracy, or (iii) NO_VERIFIED_IMPROVEMENT. Any is an acceptable technically honest result. Report *all* registered attempts and do not hide the baseline.

## Test and safety gates

- At least one adversarial future-data injection test; time-shift and label-overlap test; deliberately stale sector membership test; class-imbalance confusion test; across-fold duplicate candidate hash and repeat determinism test; action-window abstention test; status for no independent holdout.
- Run new scoped tests in both repositories, full dev Python and service offline-safe suites; Node/TS only if touched. Record the five pre-existing service-provider failures separately and verify no new failure is due to this sprint.
- Compare protected W2–W6 manifests, W3 hashes, old college evaluation result ID, V2 ledger heads, W6 no-trade seals and paper money state before/after. Fail closed on unintended mutations.
- No external credentials, Jev/Mercury calls, NSE scraping or cloud services are required. Never include secrets in fixtures, prompts, logs or commit.
- Keep this sprint in new paths wherever possible. Preserve all existing modified files and no automatic git commit.

## Completion response format

Provide (1) what changed and code paths, (2) preregistration hash, (3) full table of models h5/h20 including **raw/balanced accuracy, DOWN recall, majority baseline, delta + 95% CI, coverage, evidence tier**, (4) negative controls and sample sizes, (5) blocked items, (6) exact verification and hash results, (7) git status, and (8) the exact permissible college claim. Never call a developmental score a new unseen or forward-validated improvement.

If the codebase reveals a conflict between this handoff and authoritative prior contracts, preserve the older invariants and document the conflict rather than rewriting history.
