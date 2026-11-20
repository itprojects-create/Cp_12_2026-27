# Prereg: Model-data wiring, Steps 2-4 (bias killer continued)

**Written:** before any wiring code or rerun. Deterministic, zero tokens.
**Sources (vendored upstream, NEVER edited):** D:\Model\data\raw\delivery\*.parquet
(20 files, 2007→2026, date/symbol/qty/deliverable/pct), india_vix.csv (2009→2026),
NEW DATA TRI histories. Read via env-overridable paths; absent → loud error.

## Step 2a. Delivery panel (replaces 9MB 49-ticker slim copy as the canonical store)

New `ParquetDeliveryStore` with the SAME interface (`latest(ticker, as_of)`,
`.line(...)`): symbol = ticker minus `.NS`; **T+1 lag enforced** (latest row
strictly before as_of date — NSE publishes post-close); ma5/z20 computed
Trailing-only on lagged rows (never the as-of bar). Empty/missing → None
(caller abstains, never fabricates). Live defaults stay FROZEN this week
(Technical keeps slim CSV — prompt-input changes get their own prereg);
`positioning.py` default switches to parquet (same interface, broader cover).
Consistency diagnostic (parquet vs slim on overlapping names/dates) runs
before any Technical swap; divergence is a finding, not a bug to smooth over.

## Step 2b. Local VIX with yfinance fallback (deterministic regime input)

`regime.py` tries local `india_vix.csv` first (exact-date join, no lookahead:
row date < as_of date... note VIX file is EOD levels, same T+1 discipline),
falls back to yfinance `^INDIAVIX` when the file is missing or stale
(last row > 30d before as_of — logged). Consistency diagnostic on overlap:
agreement rate reported; <99% blocks the swap (investigate, don't average).

## Step 3. TRI official benchmarks (new reports only)

New `tri_benchmark.py`: NIFTY50 (+Momentum30) total return / CAGR between two
dates from NSE TRI histories (handles reverse-chrono + "17 Sep 2026" format,
ascending sort, T+1 join). Used in NEW report artifacts only — old JSONs keep
their hand-rolled bench numbers (audit trail frozen).

## Step 4. G1-G5 gate adoption + calibration scoping (docs + tests, zero tokens)

New `data/evaluation_gates.md`: any future DIRECTION work must clear
G1 Sharpe≥0.8 / G2 DSR≥0.95 / G3 PBO≤0.20 / G4 4-of-5 folds / G5 holdout
(adopted from the Model audit — our accuracy≥0.55 gate is retired by name for
direction claims; veto/risk work keeps its own Sharpe/MaxDD gates).
Calibration scoping (their trap lesson): `calibrate.py` docstring + tests
state it is SIZING-ONLY — isotonic maps feed position scale, never rank,
selection, or veto-table structure. Any ranking use is a prereg-level violation.

## Amendment 1 (same day, post-diagnostic — findings, not shopping)

- Delivery: slim-vs-parquet flag concordance only 61.7%, and raw pct differs
  7.0pp mean (max 30.9pp). Parquet is internally consistent
  (pct == deliverable/qty to 0.005pp) with documented pipeline + causality
  tests; slim provenance unknown. Burden reversed: **parquet is canonical for
  new paths effective immediately**; slim copy marked DEPRECATED in
  local_store docstring (behavior frozen — Technical keeps it pending its own
  prereg, since prompt-input changes are decision changes).
- VIX: full-history local vs 180d-span yahoo agree 62.5%; matched 126-bar
  windows agree 87.5% (14/16), residual = cutoff-boundary + one-bar timing.
  Explainable but not identical → **swap BLOCKED per the 99% rule**. Regime
  stays on yfinance; local VIX remains for research paths. No averaging, no
  window-matching hacks to chase the number.

## Gate

Module + synthetic tests green (T+1 lag boundary, ma/z math, missing→None,
TRI parse/sort, gate-doc completeness). Consistency diagnostics recorded
as-is. No backtest rerun in this step (reruns belong to future preregs with
their own gates).
