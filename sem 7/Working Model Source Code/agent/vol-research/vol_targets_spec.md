# Volatility-Forecasting Track — Frozen Target & PASS Spec

**Frozen:** 2026-10-05T10:51:03Z · **Status:** FROZEN — do not edit after this timestamp. Any change needs a new timestamp + written reason.
**Scope:** NIFTY index-level realized-volatility forecasting. Deterministic, no LLM. Pre-registers everything in Task Parts A–C before any backtest runs.

## A1. Universe & history (verified reachable 2026-10-05, before freezing)

- Primary: `^NSEI` (NIFTY 50 index) daily OHLCV, 2007-09-17 → 2025-12-31 (4,487 bars, yfinance).
- Auxiliary: `^INDIAVIX` daily, 2008-03-03 → 2025-12-31 (4,369 bars, yfinance).
- Index-level scope (not 50 constituents): constituent history has survivorship bias under the current ticker list and 50× download cost; dispersion across constituents is therefore a documented gap (see B6). This matches "NIFTY index" as the allowed universe option.
- No ML-ensemble research code exists in this workspace (checked `D:/QP` — only Build Plan/Report docs, no reusable walk-forward/significance code), so walk-forward + bootstrap CI are implemented here from standard definitions and documented as such.

## A2. Realized volatility definition

- Daily log returns: `r_t = ln(Close_t / Close_{t-1})` on NIFTY closes.
- Trailing 20-day realized vol (annualized): `RV20_t = std(r_{t-19..t}) * sqrt(252)`.
- Trailing 252-day median of RV20: `MED252_t = median(RV20 over the 252 bars ending at t)`.
- All trailing quantities use bars `<= t` only.

## A3. Forecast targets (frozen)

Made at forecast date `asof = t` (all inputs from bars `<= t` only). Forward windows use bars strictly after `t`.

- **Target A (binary):** forward 10-day realized vol `FWD10 = std(r_{t+1..t+10}) * sqrt(252)` vs `MED252_t` → `ABOVE` iff `FWD10 > MED252_t` else `BELOW`.
- **Target B (binary):** forward 20-day realized vol `FWD20 = std(r_{t+1..t+20}) * sqrt(252)` vs `MED252_t` → `ABOVE`/`BELOW` same rule.
- **Target C (continuous, stretch):** `FWD10` (same quantity as A's left-hand side) as a regression target.

## A4. Naive baseline (the null — NOT assumed 50%)

Vol regimes persist by construction, so the null is persistence, computed explicitly per fold:

- Binary (A/B): predict `ABOVE` iff current `RV20_t > MED252_t` (i.e. "next period's regime = today's regime").
- Regression (C): predict `FWD10_hat = RV20_t` (no-change forecast). Scored by MAE and Pearson correlation of forecast vs actual across test points.

## A5. PASS criteria for "worth building an agent around" (frozen)

1. Walk-forward OOS accuracy (binary) beats the persistence baseline with a **bootstrap 95% CI on the pooled accuracy difference (model − baseline) strictly above 0** (10,000 resamples over test points; difference of means).
2. The effect holds across **at least 2 of the 3 targets** (A, B, C-for-C the metric is correlation/MAE vs baseline with the same bootstrap-CI-above-0 rule on the MAE difference, baseline − model).
3. Stability: the accuracy difference vs baseline is **non-negative in both calm and stressed subperiods** (split test points by trailing `^INDIAVIX` 252-day percentile at forecast date: stressed = ≥85th, else calm — same cutoffs as `app/data/regime.py`), i.e. the effect is not carried by one regime alone.
4. Hundreds of folds (monthly test windows over the full history); per-fold metrics reported with CIs, not a single pooled number alone.

## B. Pre-registered feature sets (all PIT-safe, bars `<= t` only)

- F1 `vol_percentile_rank`: rank of `RV20_t` within its trailing 252-day history (strict `<`, ties-safe).
- F2 `vix_level`: `^INDIAVIX` close at/before `t`; `vix_5d_slope`: (`VIX_t / VIX_{t-5}` − 1).
- F3 `vix_term_structure_proxy`: SKIPPED — no free term-structure data; documented gap, no fabricated proxy.
- F4 `recent_extreme_move_freq`: count of flush/blowoff flags in trailing 20 days, reusing the `exhaustion_features()` rule shape (ticker-own |ret_5d| 80th-pct threshold over strictly-prior bars, 8% fallback under 60 bars) copied into `vol-research/` (no `app/` import, no `app/` modification).
- F5 earnings (`days_since_last_earnings` / `days_to_next_earnings`): SKIPPED for the long backtest — yfinance `earnings_dates` covers only recent quarters, not 2007–2025; documented gap, no fabrication.
- F6 `index_dispersion`: SKIPPED — needs survivorship-controlled constituent history; documented gap.
- Pre-VIX era handling (frozen): folds with forecast date before 2009-03 (insufficient VIX history) evaluate **non-VIX feature sets only**; VIX sets start once 60+ VIX bars exist. No backfill, no proxy.

Pre-registered model configurations (the ONLY confirmatory runs):
- M1..M4: single-feature threshold rules (F1 / F2-level / F2-slope / F4), threshold = trailing-history median fit on train only.
- M5: F1+F2 (logistic regression, train-only fit).
- M6: F1+F4 (logistic regression, train-only fit).
- M7: F1+F2+F4 (logistic regression, train-only fit).
- C-regression: same M5/M7 feature sets + persistence baseline, linear regression, MAE/correlation.
- Anything else goes in an "exploratory, not confirmatory" report section and does not count toward PASS.

## C. Walk-forward protocol (frozen)

- Monthly test windows (each calendar month 2009-04 → 2025-12 is one fold; ≈200 folds).
- Train = all history strictly before the test month, minimum 2 years; **embargo**: train ends `max(20 trading days, horizon)` before the test window's first forecast date so no forward window overlaps train.
- Forecast dates: every 5th trading day within each test month (≈4–5 points/fold, ≈900 points total).
- Metrics per target/config: pooled OOS accuracy (binary) or MAE/correlation (regression), bootstrap 95% CI on difference vs baseline, calm/stressed split, per-year stability table.
- No p-hacking: only the Section-B configurations count. Post-hoc combinations are exploratory only and need fresh held-out confirmation before counting as evidence.

## D. Decision rule (frozen)

- **GO** iff criteria A5.1–A5.4 all hold as written. The report names the passing feature/target/horizon combo as the Track 2 agent spec.
- **NO-GO** otherwise, reported as a second rigorous null result. Criteria are not loosened after seeing results.
