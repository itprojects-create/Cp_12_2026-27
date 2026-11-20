# Wave 1 — first fully reproduced strategy (EW NIFTY50 monthly rebalance)

Generated: 2026-11-12T08:57:50.935757+00:00 · Preregistered spec in `backend-extension/scripts/wave1_first_strategy.py` · Machine data: `wave1_first_strategy_reproduction.json`

**Honesty labels**: RETROSPECTIVE (archived official bars) · as-of membership → not survivor-biased · benchmark-relative excess is NOT cash profit · net figures exist only where fee truth covers them (2026-03-01+), gross-only before.

## Benchmark reproduction (official NIFTY50 TRI)

Window 2015-02-02 → 2026-09-01 (11.58 y): total return **+215.46%**, CAGR **+10.43%**, basis `total-return (dividends reinvested); price index is a separate series`.

## Equal-weight NIFTY50 (as-of membership, monthly rebalance)

| Metric | Value |
|---|---|
| Cumulative gross | **+71.07%** (CAGR +4.75%) |
| Excess vs TRI (benchmark-relative) | **-144.39%** |
| Labeled months | 133 of 141 spanned (8 abstained) |
| Net (covered months only, 2026-03-01+) | -0.0007756697165501869 over 6 months |
| Mean monthly breadth (OK/eligible) | 96.6% |

## Per year (gross, disclosed membership)

| Year | Strategy gross | TRI | Excess (rel.) | Months labeled | Mean n OK |
|---|---|---|---|---|---|
| 2015 | -12.76% | -8.51% | -4.26% | 11 | 48.0 |
| 2016 | +2.14% | +4.09% | -1.95% | 12 | 48.0 |
| 2017 | +18.14% | +29.19% | -11.05% | 12 | 47.2 |
| 2018 | -6.84% | +6.05% | -12.89% | 12 | 47.2 |
| 2019 | +0.07% | +13.11% | -13.04% | 12 | 47.2 |
| 2020 | +14.33% | +16.31% | -1.98% | 12 | 48.2 |
| 2021 | +30.27% | +27.22% | +3.05% | 12 | 49.0 |
| 2022 | +2.31% | +4.59% | -2.29% | 12 | 49.0 |
| 2023 | +17.73% | +12.56% | +5.17% | 11 | 48.5 |
| 2024 | -5.60% | +1.50% | -7.10% | 7 | 48.4 |
| 2025 | +6.92% | +11.49% | -4.58% | 12 | 49.2 |
| 2026 | -3.73% | -7.16% | +3.43% | 8 | 50.0 |

## Unadjusted corporate actions — quantified, disclosed, never imputed

**31 name-month holding windows** contain at least one overnight price discontinuity (close/prev_close < 0.65 or > 1.54 — split/bonus/demerger or consolidation shape, impossible as an ordinary move for index names), across 26 months. These windows are measured with RAW prices: no verified corporate-actions source exists locally (`app/data/corporate_actions.py`: "No verified source history is available in this repo"), so the adjustment factor abstains (UNKNOWN) and no factor is inferred from the gap.

Consequence: **the strategy-vs-TRI comparison above is NOT economically interpretable** — TRI assumes action-adjusted, dividend-reinvested holding; the strategy holds raw prices. The comparison is retained as the honest raw measurement plus this quantified caveat; suspected windows are deliberately NOT excluded (dropping e.g. a genuine crash would bias the sample upward).

Examples of detected discontinuities:

- HCLTECH: 2015-03-19 close/prev_close×0.4882; 2015-03-19 open/prev_close×0.4934
- TECHM: 2015-03-19 close/prev_close×0.2454; 2015-03-19 open/prev_close×0.2482
- INFY: 2015-06-15 close/prev_close×0.5015; 2015-06-15 open/prev_close×0.4946
- AUROPHARMA: 2015-07-20 close/prev_close×0.5087; 2015-07-20 open/prev_close×0.5038
- KOTAKBANK: 2015-07-08 close/prev_close×0.496; 2015-07-08 open/prev_close×0.4937
- BPCL: 2016-07-13 close/prev_close×0.4869; 2016-07-13 open/prev_close×0.4997
- GRASIM: 2016-10-06 close/prev_close×0.2046; 2016-10-06 open/prev_close×0.2015
- WIPRO: 2017-06-13 close/prev_close×0.4921; 2017-06-13 open/prev_close×0.494
- RELIANCE: 2017-09-07 close/prev_close×0.4972; 2017-09-07 open/prev_close×0.5002
- YESBANK: 2017-09-21 close/prev_close×0.2005; 2017-09-21 open/prev_close×0.1996

## Abstentions (recorded, never filled)

- **MISSING_SPAN** (5 months): 2024-01, 2024-02, 2024-03, 2024-04, 2024-05
- **NO_FILLS** (1 months): 2015-01
- **NO_NEXT_REBALANCE** (2 months): 2023-12, 2026-09

## Strict-membership variant (secondary)

Cumulative gross -11.59% over 133 labeled months (8 abstained; causes: MISSING_SPAN, NO_FILLS, NO_NEXT_REBALANCE).

## Notes

- Fees: full-notional round trip per name per month via `economics.py` (integer paise) — a conservative UPPER BOUND on equal-weight turnover costs; real drift-rebalanced turnover would charge less.
- The 2024 H1 archive hole produces abstention months, not gaps in the chain; the product is over labeled months only and the skipped months are listed above.
- Membership attribution (CC BY 4.0) is carried in the JSON and on every warehouse row: Jha, A. (2026), github.com/aditya-jha/nse-historical-membership.
- This reproduction may be *honestly rejected* by later waves; it is the W1 acceptance exercise for the data+fee stack, not a production signal.
