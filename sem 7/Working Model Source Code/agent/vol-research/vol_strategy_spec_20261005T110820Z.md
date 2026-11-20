# Confirmatory Vol-Magnitude Strategy — Frozen Spec

**Frozen:** 2026-10-05T11:08:20Z · **Status:** FROZEN — do not edit. No variants, one run.
**Standing:** prior NO-GO (1 of 3 targets) is not revisited. Targets A/B are not re-tested. Original 2009–2025 fold results are not cited as evidence for this test.

## A. Holdout window (genuinely unseen — proof)

- Original backtest (`vol-research/backtest.py` monthly folds; `data/point_records.csv`, 11,356 records, 175 monthly folds): max forecast date **2025-12-01T00:00:00**; its forward-label windows consume bars through ~Dec 2025.
- Fresh data pulled 2026-10-05 (after the original study): `^NSEI` 208 bars 2025-12-01→2026-10-05, `^INDIAVIX` 207 bars same range, 0 NaNs. None of these bars existed in any download used by the original study (its cache was capped at 2026-01-01 / effectively 2025-12-31).
- **Holdout forecast dates: every 5th NIFTY trading day from 2026-02-01 through 2026-09-15** (≈30 points). Rationale: all dates are >2 months after the last original-study forecast (2025-12-01), so no holdout feature bar was ever a test-fold input, and training labels never reach past Nov 2025 (see below).
- **Train pool: original-study points with forecast date < 2025-12-01 only.** December 2025–January 2026 is a dead zone, used by neither train labels (capped Nov 2025 + 20-bar windows) nor holdout features (start Feb 2026). Model fit uses zero post-2025-11 information.

## B. Target + feature set (single, cited — no re-search)

- Target: forward 10-day realized vol, continuous (original Target C formulation, identical definition).
- Feature set: **C_M5 = [F1 vol_percentile_rank, F2 vix_level]** — tied-best Target C result (MAE diff +0.0075 [+0.0049,+0.0103], shared with C_M7; C_M5 chosen on parsimony, frozen here, not re-optimized).
- Model: ordinary linear regression on train-standardized features (train-only mean/std), identical to the original C_M5. Fit once on the train pool. No refit inside the holdout.

## C. Strategy translation (frozen)

- **Priced reference (proxy, limitation flagged):** no free options-implied-vol history exists, so the reference is **trailing-60-day realized vol (RV60_t)** — the classic vol-risk-premium approximation (realized tends to run below effectively-priced vol in calm periods). This is a simplification: the synthetic payoff is direction-and-magnitude of realized-vs-reference, not an actual option P&L. Results speak to forecast value, not to a tradeable product.
- **Rule (margin m = 10%, fixed size 1 unit, pre-registered):**
  - forecast `f < ref × 0.90` → short-vol: payoff `(ref − realized_fwd10) / ref`
  - forecast `f > ref × 1.10` → long-vol: payoff `(realized_fwd10 − ref) / ref`
  - otherwise flat (no position, no cost).
- **Cost:** 0.0021 deducted per non-flat signal (project 0.21% round-trip convention translated to synthetic payoff units; documented as an approximation, same limitation as above).

## D. PASS criteria (frozen)

1. **Minimum data:** ≥20 non-flat signals in the holdout, else **INCONCLUSIVE** (not pass, not fail) — reported as-is with the stated remedy (a longer unseen window, not available yet).
2. **Sharpe:** cost-adjusted per-signal returns, annualized × sqrt(252/5) (5-trading-day signal spacing); **bootstrap (10,000 resamples, seed 7) 95% CI on the Sharpe strictly above 0.**
3. **Concentration:** top-1 trade share of total PnL ≤40% AND top-2 ≤60%, else FAIL (outlier-driven) even if the Sharpe passes.
4. **Verdict mapping:** all of (1)–(3) hold → PASS; criterion (1) unmet → INCONCLUSIVE; otherwise → FAIL. No post-hoc rule, cost, or threshold adjustment. One run only.
