# Quant Plus V3.1 — Post-W6 Accuracy Breakthrough Research Sprint

**Version:** 1.0 | **Prepared:** 2026-11-15 | **Status:** Proposal; nothing here has been run or validated.  
**Scope:** Separate experimental, read-only research lane. Do not alter the V2 ledger, W0–W6 manifests, live paper-book authority, or previously registered models.  
**Primary objective:** improve *genuine, baseline-relative* prediction of the direction of an NSE equity's future **absolute raw-price OPEN-to-OPEN return**, especially recognition of DOWN cases.  
**Secondary objectives:** improve balanced accuracy, predictive calibration and selective accuracy while reporting coverage. Optional market-relative task must remain distinctly labelled.

## 1. Recorded starting point: do not rewrite history

Source: user's post-W6 academic scoring report, reported 2026-11-15. The evidence tier is **HISTORICAL_OOF_DEVELOPMENT**. The 2022–2023 validation periods have already been examined. No fresh sealed test window is available.

- Main task: UP iff future strictly positive raw OPEN-to-OPEN return; DOWN iff strictly negative; zero/tie excluded, counted and reported. Enter at first eligible session OPEN after evidence cutoff; exit OPEN after h=5 or 20 observed NSE sessions. Never conflate with older OPEN-to-CLOSE W3 labels.
- h20 common sample n=5,071. Logistic: TN=107, FP=2,037, FN=115, TP=2,812; **57.56% accuracy**, **50.53% balanced accuracy**, **97.97% coverage of all eligible**, **56.39% unconditional accuracy**. Fixed-UP and training-majority: **57.72%** accuracy. Paired difference Logistic vs majority **−0.16 percentage points**, clustered CI **[−0.97, +1.07] pp**.
- h5 common sample n=5,077. Logistic **54.17%** vs majority **54.01%**; paired difference **+0.16 pp**, clustered CI **[−1.08, +1.22] pp**. No established improvement.
- Only approximately **26 non-overlapping h20 periods** and **104 h5 periods**; 5,000 correlated stock-label rows are *not* 5,000 independent trials.
- Raw bars, incomplete corporate actions and dividends, membership reliability gaps, two missing historical spans, incomplete fees, and no untouched holdout remain important limitations. W6 forward study contains **zero genuine observation sessions** and is **NO_ELIGIBLE_STRATEGY**.
- All statements such as “AI achieved 60% independent accuracy,” “profitable,” or “better than baseline” remain **prohibited** unless newly earned by appropriate evidence.

## 2. Research premise

The current model predicts UP roughly 95.6% of the time, correctly identifying only 107/2,144 DOWN cases on the common h20 sample. It captures the general positive class prevalence, not convincingly stock-specific predictive skill. A better model should distinguish market direction from individual security excess return and learn context-dependent relationships without learning the evaluation period.

There is no credible mechanism to guarantee +3, +5 or +10 percentage points. **A negative or inconclusive result is an acceptable research outcome and must be preserved.**

### Scientific inspiration (not evidence of Quant Plus performance)

1. Gu, Kelly & Xiu, *Empirical Asset Pricing via Machine Learning*, Review of Financial Studies (2020). Nonlinear interactions and stock predictors including momentum, liquidity and volatility: https://doi.org/10.1093/rfs/hhaa009.
2. NSE Nifty200 Momentum 30 official description: volatility-adjusted six- and twelve-month momentum. Use as a *hypothesis* and source of methodological inspiration, not a claim of index replication: https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30.
3. Wang & Lera, *Meta-Learning for Return Prediction in Shifting Market Regimes* (revised 2026): regime-conditioning can help on other equity markets, not proven here: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5022829.
4. Bailey & López de Prado, *The Deflated Sharpe Ratio*, Journal of Portfolio Management (2014): repeated testing can manufacture impressive-looking winners: https://doi.org/10.3905/jpm.2014.40.5.094.
5. Selective classification literature: accuracy conditional on answering must always be displayed alongside coverage: https://raw.githubusercontent.com/mlresearch/v230/main/assets/garcia-galindo24a/garcia-galindo24a.pdf (verify full publication metadata if citing formally).

## 3. The experiments: low-cost first, research-heavy last

### E0. Baseline and target audit (P0)

Freeze target and horizon semantics exactly as post-W6 scoring. Recompute the previously reported confusion matrix from persisted predictions (or replicate deterministically) and reconcile denominators. Produce fixed-UP, fixed-DOWN, train-majority (not full-sample majority), previous Logistic/Ridge/HGB, and a simple index-conditioned majority predictor trained in-fold. Check how many outcomes are exactly zero, action-blocked, no-label, weak-membership and previously seen. Fail if numbers do not reconcile.

### E1. Correct the overwhelming UP bias (P0)

Implement train-only class weights and regularization in Logistic; compare plain and class-weighted shallow HGB; train-only probability calibration (Platt/sigmoid or isotonic only if samples warrant); threshold optimization for balanced accuracy. Tune within each training fold, **not** using the outer evaluation dates. Report UP prediction rate, DOWN recall/specificity, precision by class, macro-F1, MCC, Brier score and calibration. Class weighting can increase DOWN recall while *reducing* overall accuracy; report the trade-off.

### E2. Market regime and two-head model (P0 research candidate)

Create a benchmark-context head `P(market_UP over same h)` from *only evidence available at the cutoff*; create a security-specific head for `P(stock excess return > 0)` or next-horizon excess return using correctly time-aligned market basis. Then combine both using a small train-only calibrator to predict `P(stock absolute raw OPEN-to-OPEN UP)` **without algebraic independence assumptions**. Two-head blending is not a guaranteed conversion: the relationship is learned and must be tested. The main official scoring target remains unchanged. A market-relative classifier is *secondary*, reported in a different column.

If verified matching benchmark OPEN-to-OPEN history is missing, mark the relative head `DATA_BLOCKED_BENCHMARK_BASIS`; do not substitute NIFTY TRI or close-to-close prices for the target and do not use future market returns as features.

Build deterministic regime descriptors from observed pre-cutoff data only: index/tradable-proxy 20/60d price trends, realized volatility percentiles, cross-sectional breadth, dispersion, correlation, VIX if verified, and market excess-volume. Use simple 2–3 state buckets before attempting mixture-of-experts. Fit bucket thresholds on training history only; no hindsight crisis labels.

### E3. Point-in-time cross-sectional features (P1)

Per decision date, compute eligible-universe ranks for ret_5/20/60/126/252, volatility 20/60, volume ratios, 52-week proximity, normalized range, short-term reversal, beta and residual momentum *if* the benchmark history is valid. Rank only in members actually knowable at that cutoff; annotate weak membership. No sector-relative features until verified PIT sector map exists; do not assume today's Nifty classification was known historically. Missing fields create typed skips; never zero-impute unknown availability.

### E4. Controlled nonlinear and ensemble comparison (P1)

Start with shallow HGB (max leaf nodes, fixed regularization), Ridge/Elastic Net for continuous return plus train-only calibrated sign, and Logistic class-weighted variants. Only if justified and installed, evaluate LightGBM/CatBoost with a pinned dependency/version and bounded CPU budget. No GPU, no large LLM fine-tuning, no expensive transformer training on an 8GB laptop by default. Avoid dozens of random architectures.

An ensemble must use **out-of-fold base predictions from the inner training period only**. No stacking on 2022–2023 viewed outer OOF outcomes. Include a diversity report: pairwise correlation of residuals, incremental gain over single model, degradation in worst regimes.

### E5. Selective directional prediction (P1)

Build a calibrated answer/no-answer policy chosen only from past training samples. Show coverage at preset 100%, 75%, 50%, 25%, and (only if adequate counts) 10%. Also show UP and DOWN coverage separately, model abstention counts, **unconditional accuracy** where abstentions remain in denominator, and baseline comparisons at the *same coverage* (including a benchmark confidence score if available). A 60% hit rate on 5% of stocks is not 60% overall accuracy. Do not cherry-pick the confidence threshold after reviewing a validation result.

### E6. Evidence challenger / anti-leakage battery (P0, all experiments)

Include label-window overlap tests and purging for h20; time-zone/cutoff and execution checks; train-only normalization, scaling, calibration and thresholding; swap ticker identities to test memorization; temporal-shuffle/label-permutation/noise controls; no same-bar future open; no source fetched after cutoff; bootstrap by decision sessions and non-overlapping periods; worst-year/regime analysis; missingness and weak-membership sensitivity; fixed-UP and training-majority baselines; actual number of model/grid hypotheses disclosed; candidate family stability before any later independent seal.

## 4. Evaluation contract and the hard truth about 'unseen'

**Dataset split reality:** 2022–2023 is already viewed development data. 2024–2026 historical W2 holdout was also revealed, and cannot simply be renamed unseen. Older data used to train prior models is not an untouched holdout either. True new independent evidence should be prospective, generated after a new preregistration and model/code freeze, with genuine future first-seen market observations and naturally matured h5/h20 labels.

Research stages:

- `TRAIN_ONLY_INNER`: Tune on earlier training blocks, strict chronological order, purge by actual label end and embargo where applicable.
- `HISTORICAL_OOF_DEVELOPMENT`: Re-score newly generated predictions on known 2022–2023 development tiles. Report *all candidates*, including failures, with no 'independent' language.
- `FROZEN_FORWARD_PENDING`: Create an irrevocable model choice and signed configuration including feature/label/data/code hashes, timestamps, and a clear decision clock. If no eligible PIT market feed exists, the state stays `FORWARD_NOT_STARTED` rather than simulating time.
- `FORWARD_MATURED`: Score only when 5/20 observed NSE sessions have elapsed, with complete evidence and no post-hoc changes; an isolated academic prediction stream may run read-only even while the W6 trading stream has `NO_ELIGIBLE_STRATEGY`. It must **not** bypass W6 trading/economic eligibility.

Metrics for each horizon, each candidate and each subset: (i) raw accuracy, (ii) balanced accuracy, (iii) DOWN recall and UP recall, (iv) macro-F1, (v) Matthews correlation coefficient, (vi) Brier and calibration, (vii) exact answer count/eligible count/abstention count/coverage, (viii) session-clustered and block-bootstrap 95% CIs, (ix) *paired* Δ vs fixed-UP and train-majority baselines with CIs, (x) fold/year/regime performance and (xi) effective non-overlapping time periods. No independence assumptions across securities on one session.

Use explicit verdicts:

- `ENGINEERING_PASS` / `ENGINEERING_FAIL` for reproducibility, safety and test verification.
- `DEVELOPMENT_ABOVE_50_POINT_ESTIMATE` only if historical OOF score exceeds 50%; **does not imply model skill**.
- `DEVELOPMENT_BASELINE_ADVANTAGE_UNESTABLISHED` unless paired interval strictly positive; distinguish promising *point estimates*.
- `INDEPENDENT_FORWARD_UNAVAILABLE` until truly new sealed outcomes mature; never infer a fresh holdout from existing 2022–2026 data.
- `ECONOMICS_DATA_BLOCKED` until rights, fees, actions, fill and benchmark bases pass W6 gates.
- `NO_ELIGIBLE_STRATEGY` continues; no order authority for any academic diagnostic.

## 5. Bounded research protocol

Before running new experiments, write `accuracy_sprint_preregistration.json` and hash the initial hypothesis, dataset boundaries, model family list, hyperparameter grid, thresholds, primary metric and selection rule. Keep the grid small and fixed (e.g. <= 12 predefined family/feature configurations × 2 horizons, each with <= 4 inner hyperparameter combinations). Never rewrite a preregistration. Unplanned ideas get a new linked preregistration ID and are labelled exploratory. Store all attempts in append-only research journal and report the number of tries. Prioritize E0/E1/E2 before E3/E4/E5, but do not announce a winner after trying a hundred variations.

Suggested model-selection order within inner time-validation only:
1. Meet basic completeness: calibrated probabilities, strict point-in-time evidence, >=50% of positive/negative class represented, no hidden abstentions.
2. Maximize balanced accuracy, subject to predeclared minimum raw-accuracy floor (e.g. train-majority minus 2pp), with ties decided by smaller worst-regime loss, then lower complexity.
3. Compare against baseline as a paired observation-by-decision-date comparison. Return NO_PREDICTIVE_IMPROVEMENT if none passes.

The comparison with the historical majority is a *developmental comparison*. Primary forward hypotheses and practical acceptance thresholds must be sealed before future outcomes are observed.

## 6. Reproducibility and files

Add new isolated package `backend-extension/quantplus_intelligence/research_v3/accuracy_sprint/` with contracts, target audit, PIT features, models, regime, calibration, selective, tests, evaluation, and export. Add a single orchestrator `backend-extension/scripts/accuracy_sprint_run.py`. Prefer pure Python/scikit-learn and existing dependencies; no need to wire a UI or mutate frontend trading contracts.

Deliver under `reports/alpha_v3_1/accuracy_sprint/`:

1. `preregistration.json` + seal/hash + immutable link to baseline post-W6 result ID `32062fc4437a397be2813df19bccda31c061d8de9e1501c208884dc0f8190c2d`.
2. `baseline_reconciliation.json` with exact prior confusion matrices and denominators.
3. `pit_data_eligibility_and_leakage.md`.
4. `model_and_feature_ablation.csv` / `.json` with every registered attempt.
5. `directional_accuracy_comparison.json` / `.md` and confidence intervals.
6. `confusion_matrices.png`, `risk_coverage_curves.png`, `regime_comparison.png`, `calibration.png` (only grounded numbers; mark data-blocked explicitly).
7. `forward_readonly_protocol.md` + an independently sealed academic prediction-stream contract; do not claim forward sessions until observed.
8. `college_results_section.md` with appropriate disclaimers; choose the headline *by evidence tier*, not by best-looking number.
9. `acceptance_report.md`, `test_results.md`, `reproducibility_manifest.json`, manifest verifier, and diff preserving W0–W6 hashes.

Clean-room regression requirements: read the canonical W3 feature hash, original W3 label hash, post-W6 academic OPEN-to-OPEN label hash, and all earlier report and ledger digests **from their existing immutable manifests** in the checked-out repository. Do not encode any transcription of a hash from this document as authoritative. Compare W2–W6 manifests and the academic baseline result against fresh readbacks; never regenerate old artifacts with new code or silently overwrite an old seal. Any new digest must represent a new immutable version with a link to its predecessor.

## 7. Explicit no-go rules

- No backdating events, cherry-picking dates, creating synthetic success rows, metric inflation or changing labels after seeing outcomes.
- No use of future close/open/benchmark prices, present-day sector identities or current constituents as historical feature inputs.
- No multiple-selection winner named 'independent' when selected using the validation tiles.
- No changing the college paper's reported original result without a new signed revision explaining why.
- No external model/provider calls required. Jev/Mercury may only review already grounded research summaries under existing read-only tools if later approved; their prose is not a label or statistical benchmark.
- Do not ask for or log credentials, expose keys, touch money state, enable live trading, push/commit automatically or alter 12+ user-modified files.
- If adding feature data requires unverified legal sources, mark the experiment `DATA_BLOCKED` and proceed with available features.

## 8. What success realistically means

**Best-case research outcome:** A model obtains higher raw and balanced accuracy, materially improves DOWN recall, maintains usable coverage, and beats the majority baseline with a paired interval suggesting nonzero improvement in *new independent forward evidence*. That would be meaningful, but cannot be promised.

**Credible immediate academic outcome:** A deeper developmental comparison, confusion matrices, ablations, transparent baselines and an explanation of why the existing 57.56% did not yet outperform 57.72%. This is still a valid and substantial college engineering result.

**Absent fresh observations:** label any improvement as `HISTORICAL_OOF_DEVELOPMENT`. Do not substitute paper P&L or Jev's synthetic goldset accuracy for directional accuracy.
