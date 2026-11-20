# Preregistration: Trend Core v4 (top-K + baked veto + bench correction)

**Written:** 2026-10-07, BEFORE any v4 backtest was run.
**Frozen bases:** v2 (`trend_core.py`) and v3 (`trend_core_v3.py`) untouched.
**New module:** `app/core/trend_core_v4.py`.
**Motivation (measured, not theorized):** `data/core_backtest_v3_broad.json` —
391 names, exposure 5.5%, 113 switches. The v3 gross-cap scale-down spreads 100%
over ~391 qualifiers into dust (~0.26% each) that the 0.015 turnover filter then
blocks. The rule as coded cannot hold a broad book. Fix: select BEFORE sizing.

## Changes (one set, two runs — NIFTY50 + broad — no sequential tuning)

1. **Top-K selection (K=50, frozen):** at each rebalance, rank qualifiers
   (trend UP + 60d mom>0 + vol>0, minus STRESSED-new/blackout blocks) by 60d
   momentum descending, keep top 50. Only ranked names get targets. Held names
   that fall out of top-50 target 0 (exit via normal turnover/min-hold).
   On NIFTY50 (36 names) top-50 binds rarely => near-v3 behavior (comparability).
2. **Baked veto (same frozen table, reused not re-tuned):** `veto_fraction`
   from `app/core/overlay.py` applied to NEW entries only, after tier/sector/
   gross caps, before vol-target/turnover. Veto may only shrink (asserted).
3. **Bench correction (math fix, disclosed):** v2/v3 bench used
   `prod(1 + (ret_i)/N)` which explodes with N (broad bench_cagr 119.9% —
   artifact, never cited). v4 bench = mean of individual total returns,
   CAGR from that. Old reports keep old numbers (audit trail); v4 reports the
   corrected bench alongside the note.
4. Everything else identical to v3: VIX filter, turnover 0.015, 20d min-hold,
   earnings-blackout param (skipped in scripts, disclosed), 10% port vol-target
   (down-only), tier caps 10/5/3%, sector 25%, GROSS_CAP 1.00, same costs.

## Gates (recorded as-is, no re-tune)

* NIFTY50: `Sharpe_v4 >= Sharpe_v3 (0.705) OR MaxDD_v4 < MaxDD_v3 (12.46%)`,
  AND `exposure_v4` within 5pp of v3 (no regime change on narrow book).
* Broad: `exposure_v4 in [20%, 80%]` (must hold a real book, fixes 5.5%),
  AND `Sharpe_v4 > 0` with MaxDD < 20% (sanity, not excellence).
* If FAIL: ship v3-NIFTY50 + overlay (current best), v4 stays experimental.

## Invariants (tests/test_core_v4.py)

* Nonzero targets per rebalance <= 50 always.
* Prefix-invariance (no lookahead); gross <= 1.00; veto never increases a target.
* Bench math: single-name bench CAGR == that name's own buy-hold CAGR (±1e-9);
  391-name bench is finite and < 100%.
