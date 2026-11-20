# Preregistration: Trend Core v3 (single change set, one re-run)

**Written:** 2026-10-07, BEFORE any v3 backtest was run.
**Frozen base:** `app/core/trend_core.py` v2 (GROSS_CAP=1.00, prereg v2).
**New module:** `app/core/trend_core_v3.py` — v2 file untouched (audit trail preserved).

## Changes (all five, one run — no sequential tuning)

1. **VIX regime filter (code, PIT):** `STRESSED + trend==UP -> no NEW entries` (holds allowed).
   `ELEVATED + UP -> gross capped at 50%`. Regime from trailing VIX percentile
   (50th/85th, same as `app/data/regime.py`), computed on passed-in VIX series only.
2. **Turnover filter:** trade only if `|delta| > 0.015`; min 20 trading-day hold
   (new entries blocked within 20d of last change for that name).
   Target: `switches <2000` (v2: 3968), `costs <3.5%` (v2: 6.4%).
3. **Earnings blackout:** no NEW entries when bar `t` is within 10 trading days
   before a known result date for that name. Holds pass through. Blackout set
   passed in per-name (`dict[name, set[bar_idx]]`); absent => filter skipped
   with disclosure (never assumed).
4. **Portfolio vol target:** scale gross to 10% annualized port vol at each
   rebalance (computed on trailing 20d portfolio daily rets). Never scales UP
   beyond v2 targets — only down. Combined with GROSS_CAP=1.00.
5. **Tier + sector caps:** NIFTY50 name max 10%, NIFTY500-non50 max 5%, SME max 3%;
   sector gross max 25% (proportional scale-down within breaching sector).
   Sector map passed in; absent => single-sector assumption (no cap binds).

## Gate to proceed (recorded as-is, no re-tune)

* `MaxDD_v3 < MaxDD_v2 (16.35%) OR Sharpe_v3 > Sharpe_v2 (0.698)`, AND
* `2022_ret_v3 > 2022_ret_v2 (-10.25%)` (whipsaw must improve).
* If FAIL: ship v2, do not tune. Overlay builds on whichever core passes.

## Window / universe

* Same window as v2 (`2021-01-01..2026-10-01`, 1420 bars) for comparability.
* Tiered: NIFTY50 validated; NIFTY500/SME via `app/data/universe.py` lists
  (missing file => loud error). SME paper-only disclosure applies.

## Invariants (tested in tests/test_core_v3.py)

* Prefix-invariance (no lookahead): truncating all series to [:k] never changes bars <k.
* Gross ≤ 1.00 always; turnover filter never increases switches vs v2 on same input.
* Blackout never creates a position, only blocks new entries.
* Costs bounded by switches × COST_PER_SIDE × max_size.
