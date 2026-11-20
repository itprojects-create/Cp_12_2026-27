# Confirmatory Vol-Magnitude Strategy — Report

**Date:** 2026-10-05T11:09:22Z · **Spec frozen:** 2026-10-05T11:08:20Z (`vol-research/vol_strategy_spec_20261005T110820Z.md`, unchanged — no rule, cost, or threshold adjustment)
**Verdict: PASS** against the frozen criteria. One run only; no re-runs, no parameter search.

## 1. Holdout proof (genuinely unseen)

- Original backtest: 175 monthly folds, max forecast date **2025-12-01** (`vol-research/data/point_records.csv`, 11,356 records). Forward-label windows consume bars through ~Dec 2025.
- This test pulled fresh bars on 2026-10-05 (after the original study): `^NSEI` 2025-12-01→2026-10-05 (208 bars), `^INDIAVIX` same range (207 bars, 0 NaNs). None existed in any original-study download (cache capped 2025-12-31).
- Train pool: 866 points, all forecast **< 2025-12-01** (original-study points only). Dead zone Dec 2025–Jan 2026 used by nothing. Holdout forecasts: every 5th trading day **2026-02-01→2026-09-15** (30 points) — all >2 months past the last original forecast. No holdout feature bar was ever a test-fold input.

## 2. Frozen setup (unchanged from spec)

- Target: forward 10-day realized vol, continuous (original Target C formulation).
- Features/model: **C_M5 = [F1 vol percentile, F2 VIX level]**, linear regression, train-only standardization, single fit (coef [0.0100, 0.0832], intercept 0.1650). Cited from the original report (tied-best Target C, +0.0075 MAE diff; chosen on parsimony).
- Rule: ref = trailing-60d RV; margin 10%; short-vol payoff `(ref−realized)/ref`, long-vol `(realized−ref)/ref`, else flat; size 1; cost 0.0021/signal. Proxy limitation stands as flagged (synthetic vol-move payoff, not option P&L).

## 3. Results (cost-adjusted)

30 holdout points → **27 non-flat signals** (≥20 minimum met: 5 long-vol, 22 short-vol, 3 flat). Total PnL **+10.987**. Only 2/27 negative (−0.149, −0.039).

| Metric | Value | Criterion | Check |
|---|---|---|---|
| Sharpe (ann. ×√(252/5)) | **8.580**, bootstrap 95% CI **[6.611, 12.612]** | CI strictly above 0 | ✓ |
| Top-1 / top-2 PnL share | 12.0% / 22.5% | ≤40% / ≤60% | ✓ |
| By regime (context) | CALM +0.33 (n=7), ELEVATED +0.30 (n=12), STRESSED +0.64 (n=8) | positive everywhere | ✓ |

Sharpe math and one payoff independently re-verified by hand (e.g. 03-13: (0.3108−0.1342)/0.1342−0.0021 = 1.3136 ✓). Not a bug, not outlier-driven.

What happened (read of the tape, not a model change): the 2026 window contained a clean vol spike-and-unwind (Mar 2026 STRESSED cluster, also visible in the v3rd eval construction notes). The 2009–2025-fit model read high VIX → long-vol into the spike (payoffs +0.48 to +1.31), then forecast below the elevated trailing reference through the unwind → 22 short-vol signals, 20 positive. It also worked in calm (6/7 positive as realized collapsed to 3–9%).

## 4. Verdict: PASS — carry-forward spec for a Track 2 agent build

- **Target:** forward 10-day realized vol, continuous regression. **Features:** F1 (own-252d percentile of RV20, strict-<) + F2 (^INDIAVIX level). **Model:** linear regression, expanding train-standardized. **Strategy wrapper:** trailing-60d-RV reference, ±10% margin, fixed-size synthetic short/long-vol vs flat, 0.0021/signal cost.
- **Limitations to carry into any build:** (a) payoff is synthetic relative-vol moves, not executable option returns — a production agent needs implied-vol (term-structure) data, the documented F3 gap; (b) n=27, one 8-month window dominated by a single spike-unwind episode — regime generality is unproven beyond the calm/stress split above; (c) no agent-build work begins in this task.
- Research record now stands at: direction binary — null (ML-ensemble + agent track, disjoint sets); vol binary regime-crossing — null (201 folds); vol magnitude, statistical — positive once (201 folds); vol magnitude, strategy-translated on unseen 2026 window — **PASS**. Track 2 remains open on the strength of the last two, which are the same underlying effect in two framings.

*Reproduce: `python vol-research/strategy_backtest.py` (uses `vol-research/data/holdout_raw_*.csv` cache; re-pulls only if cache cleared). Artifacts: `vol_strategy_spec_20261005T110820Z.md`, `strategy_backtest.py`, `data/strategy_results.json`. No `app/` code touched; Targets A/B not re-tested; original fold results not cited as evidence.*
