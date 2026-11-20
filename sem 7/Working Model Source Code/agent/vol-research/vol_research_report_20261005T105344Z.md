# Volatility-Forecasting Track — Research Report

**Date:** 2026-10-05T10:53:44Z · **Spec frozen:** 2026-10-05T10:51:03Z (`vol-research/vol_targets_spec.md`, unchanged)
**Verdict: NO-GO** against the pre-registered criteria. One of three targets (C) clears its bar; the criterion requires two. Criteria were not loosened. No exploratory combination is reported as confirmatory.

## 1. Targets & PASS criteria (as frozen, unchanged)

- Universe: `^NSEI` 2007-09-17→2025-12-31 (4,487 bars) + `^INDIAVIX` from 2008-03-03 (4,369 bars), yfinance, cached `vol-research/data/`.
- RV = annualized std of daily log returns, 20d trailing; median = trailing 252d median of RV20.
- A: fwd-10d RV vs trailing median (binary). B: fwd-20d RV vs trailing median (binary). C: fwd-10d RV, regression.
- Baseline (explicit null): persistence — binary: predict today's regime (`RV20_t > MED252_t`); regression: no-change (`RV20_t`). NOT assumed 50%.
- PASS: (1) bootstrap 95% CI on pooled (model−baseline) strictly above 0; (2) holds on ≥2 of 3 targets; (3) non-negative in both calm and stressed (`^INDIAVIX` ≥85th pct) subperiods; (4) hundreds of folds.

## 2. Features & no-lookahead tests

Standalone `vol-research/features.py` (rule shapes copied from `app/data/regime.py` strict-`<` ranking and `app/agents/features.py` exhaustion flags; zero `app/` imports, zero `app/` modifications). Tested before any backtest: `test_features_lookahead.py` — **all 5 pass** (append-future invariance, perturb-future invariance, flat-tie ranks 0, short-history defaults, engineered −12% flush). Backtest additionally asserts vectorized flags match the loop reference on 25 sampled bars (passed).
- F1 vol percentile, F2 VIX level + 5d slope, F4 extreme-move frequency (all built). F3 term-structure, F5 earnings, F6 dispersion: skipped with documented gaps (no free long-history data; nothing fabricated). Pre-VIX folds use non-VIX sets only (no backfill).

## 3. Walk-forward results (201 folds, 2009-04→2025-12, ≈819 forecast dates, 20-bar embargo, train-only fits)

### Binary A — fwd-10d regime vs median (base rate ABOVE ≈ 0.43; persistence baseline ≈ 0.68)

| Config | n | acc model vs base | diff [95% CI] | sig | calm | stressed (n≈113) |
|---|---|---|---|---|---|---|
| M1 vol pct | 712 | 0.676 vs 0.677 | −0.0014 [−0.0225,+0.0197] | ns | −0.0083 | +0.0354 |
| M2 vix level | 709 | 0.676 vs 0.676 | +0.0000 [−0.0423,+0.0451] | ns | +0.0185 | −0.0973 |
| M3 vix slope | 706 | 0.555 vs 0.674 | −0.1190 [−0.1686,−0.0680] | ns (worse) | −0.1061 | −0.1875 |
| M4 extremes | 712 | 0.607 vs 0.677 | −0.0702 [−0.1067,−0.0337] | ns (worse) | −0.0801 | −0.0177 |
| M5 vol+vix | 709 | 0.678 vs 0.676 | +0.0028 [−0.0212,+0.0268] | ns | +0.0151 | −0.0619 |
| M6 vol+extr | 712 | 0.695 vs 0.677 | +0.0183 [−0.0056,+0.0407] | ns | +0.0284 | −0.0354 |
| M7 all | 709 | 0.680 vs 0.676 | +0.0042 [−0.0197,+0.0296] | ns | +0.0117 | −0.0354 |

Best (M6) misses significance (CI crosses 0) and flips negative in stress. Per-year M7 beats baseline 7/15 years (coin flip).

### Binary B — fwd-20d regime vs median (persistence baseline ≈ 0.71)

| Config | n | acc model vs base | diff [95% CI] | sig |
|---|---|---|---|---|
| M1 vol pct | 712 | 0.712 vs 0.714 | −0.0014 | ns |
| M2 vix level | 709 | 0.630 vs 0.712 | −0.0818 [−0.1241,−0.0395] | ns (worse) |
| M3 vix slope | 706 | 0.561 vs 0.711 | −0.1501 | ns (worse) |
| M4 extremes | 712 | 0.640 vs 0.714 | −0.0730 | ns (worse) |
| M5 vol+vix | 709 | 0.715 vs 0.712 | +0.0028 [−0.0099,+0.0155] | ns |
| M6 vol+extr | 712 | 0.715 vs 0.714 | +0.0014 | ns |
| M7 all | 709 | 0.708 vs 0.712 | −0.0042 | ns |

No config significant on A or B. The binary regime-crossing question is fully explained by persistence.

### Regression C — fwd-10d RV level (n=709)

| Config | MAE model vs base | diff (base−model) [95% CI] | sig | corr | calm diff | stress diff |
|---|---|---|---|---|---|---|
| C_M5 (vol+vix) | 0.038 vs 0.045 | +0.0075 [+0.0049,+0.0103] | **SIG** | +0.681 | +0.0047 | +0.0227 |
| C_M7 (+extr) | 0.038 vs 0.045 | +0.0075 [+0.0048,+0.0103] | **SIG** | +0.679 | +0.0047 | +0.0222 |

Continuous vol level IS forecastable better than no-change (~16% MAE reduction, holds in both regimes, stronger in stress). This is 1 of 3 targets — necessary but not sufficient under the frozen rule.

## 4. Verdict: NO-GO

Criterion (2) requires ≥2 of 3 targets; only C clears its bar. A and B fail significance on every pre-registered configuration across 201 folds. The criteria are reported as written, not revisited.

## 5. What this means (no agent build follows — task ends at this report)

- The agent-tradable question (high/low vol regime positioning, Targets A/B) shows **no edge over "today's regime persists"** — the same rigorous null as the direction track, now extended to binary vol regimes on disjoint methodology and 16× the folds.
- The one positive thread (Target C level forecasting, MAE 0.038 vs 0.045, corr +0.68) is a candidate input feature for risk-sizing, not a standalone regime agent: it predicts *how much* vol, not a side to take, and its binary implication adds nothing over persistence.
- If Track 2 is ever revisited, the pre-registered starting point would be C_M5 (F1+F2, 10d horizon) — but under these criteria it does not clear the bar for an agent build, and any new binary-regime idea needs a fresh held-out confirmation before counting.

*Reproduce: `python vol-research/test_features_lookahead.py`, then `python vol-research/backtest.py` (uses disk cache; full history re-download only if cache cleared). Artifacts: `vol-research/vol_targets_spec.md` (frozen), `features.py`, `targets.py`, `data.py`, `backtest.py`, `data/results.json`, `data/point_records.csv`. No file under `app/` was read-for-import or modified; `app/` patterns were copied with attribution.*
