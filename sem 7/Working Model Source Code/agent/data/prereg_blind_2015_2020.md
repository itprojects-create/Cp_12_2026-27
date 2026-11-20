# Preregistration: BLIND test on 2015-2020 (genuinely unseen data)

**Written:** BEFORE any 2015-2020 data was fetched, viewed, or measured in this
project. This is the un-burning test the verification report demanded.

## Why this window is blind

Every v4 parameter (MA20/50, 60d momentum, vol targeting, veto thresholds
40%/8%/-0.5%, topK=50, turnover 0.015, VIX 50th/85th cutoffs) was chosen on
2026-10-06 with zero measurements on pre-2021 data — no backtest, no paper run,
no diagnostic has ever touched 2015-2020 in this repo. The designers know as
public history that COVID crashed markets in Mar 2020; no parameter was fit to it.

## Why this window is HOSTILE (stronger than unseen)

- Mar 2020: NIFTY -38% in weeks (circuit-filter era the rule never saw in design)
- 2016 demonetisation drawdown; 2018-2019 midcap/smallcap bear market
- Design window (2021-2026) was a largely bull tape; this window contains two
  real bears. A bull-fit rule should fail here — that is the point.

## Protocol (frozen)

- Window: 2015-01-01..2020-12-31. Rule: app/core/trend_core_v4.py UNTOUCHED.
  Params: identical to shipped (TOP_K=50, same veto table, same caps/costs).
- Universes: narrow (NIFTY50 list, ≥90% coverage) + broad (NIFTY500 list, ≥90%).
- ONE run per universe. Whatever prints is recorded as-is. No re-runs, no
  tweaks, no "data issue" re-rolls unless the script crashes before producing
  numbers (mechanical failure only, logged).
- Runner change ONLY: --start/--end CLI flags on the v4 script (defaults
  unchanged: 2021-01-01..2026-10-01). Output filenames carry the window.

## Gates (PASS/FAIL predeclared)

- Narrow: CAGR > 0 AND MaxDD < 0.30 AND total costs < 10% of book.
- Broad: same three AND avg exposure in [20%, 80%].
- Reference (not a gate): buy-hold on the same universe; the rule is expected
  to trail B&H in bull years — the claim under test is survival + positive
  risk-adjusted return through bears, not outperformance.

## Known biases (disclosed BEFORE seeing numbers)

- Survivorship is WORSE here than in 2021-2026: the 2026 NIFTY500 list applied
  11 years backward silently drops every 2015 member that died/exited since
  (direction: inflates; magnitude: unquantified, larger than the 5-name case).
- Yahoo 2015-2020 bars are older/more revision-prone; ^INDIAVIX early history
  may be thin (CALM fallback discloses itself in output).
- Trial registry grows by 2 (blind-narrow, blind-broad) for all future DSR math.

## Verdict mapping (written before numbers exist)

- PASS both: v4 graduates to "survived an unseen bear regime" — forward paper
  remains the live test, but the rule earns its paper allocation.
- FAIL either: the 2021-2026 numbers are declared bull-tape artifacts; the money
  path reverts to v3-narrow + overlay (the smallest surviving claim) and v4
  returns to experimental status. No third option, no renegotiation.
