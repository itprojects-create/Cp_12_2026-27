# W5 Historical Crisis Replay — India COVID-19 selloff

**Evidence time:** 2026-11-14T09:05:10.030883+00:00  
**Label:** `HISTORICAL_RETROSPECTIVE` · `PRICE_ONLY` · `PARTIAL` · `RESEARCH_ONLY`  
**Result ID:** `0da0487137ee19c763a9c24035bb6d94ff5bb1fc9d523c5acc539540dc1fd966`

This is a descriptive replay of observed historical prices for a hypothetical portfolio. It is
**not** a forecast, future probability, expected return or live-executable instruction.

## Event and source

- Window: **2020-01-14 through 2020-03-23**, recovery observation through 2020-12-31.
- Context anchor: *Reserve Bank of India, Financial Stability Report, July 2020*;
  `https://www.rbi.org.in/Scripts/PublicationReportDetails.aspx?ID=1153` (official page resolved 2026-11-14), with Chapter I documenting
  January panic sell-offs and March stress. Exact 14 January / 23 March boundaries were separately
  cross-checked against a search-indexed supporting chronology (direct article fetch returned 403)
  and both align to local official sessions.
- Local observations: W1 official bhavcopy archive, captured retrospectively on 2026-09-18.
- Benchmark context: NIFTY50 TRI **-38.27%** over the boundary dates. This is a total-return
  index and therefore basis-incompatible with raw price-only holdings; no relative economic
  conclusion is computed.

## Hypothetical mapping

| Current symbol | Weight | Mapping | Status | Boundary price-only change |
|---|---:|---|---|---:|
| `RELIANCE` | 35% | `SAME_INSTRUMENT` | `OBSERVED_PRICE_ONLY` | -42.20% |
| `TCS` | 25% | `SAME_INSTRUMENT` | `OBSERVED_PRICE_ONLY` | -24.34% |
| `HDFCBANK` | 25% | `SAME_INSTRUMENT` | `OBSERVED_PRICE_ONLY` | -40.17% |
| `JIOFIN` | 15% | `NO_HISTORICAL_MATCH` | `NO_HISTORICAL_MATCH` | UNAVAILABLE |

Supported same-ISIN weight is **85%**; unmatched JIOFIN weight is
**15%**. The unmatched weight is not assumed to be cash or flat, so
full-portfolio return is `UNAVAILABLE`.

## Observed supported-component metrics

- Common observed stress sessions: **48/48**
  (100.0%). No forward fill.
- Supported-component boundary price change: **-36.35%**.
- Peak-to-trough drawdown: **-37.16%**, from
  2020-01-17 to 2020-03-23.
- Worst observed day: **-10.97%** on
  2020-03-23.
- Price-only recovery: **OBSERVED** on
  2020-07-03 after
  68 observed sessions.
- Data quality: `LOW_PRICE_ONLY_ACTION_COVERAGE_UNKNOWN`. Corporate-action coverage is incomplete; no split,
  bonus, demerger or dividend factor is invented.

Changing JIOFIN from `NO_HISTORICAL_MATCH` to an explicit HDFCBANK sector proxy mints result
`301d80ca7f1bc83024225e316411cba3955b34ddf85dfe4b91d9c1c79ab668ec` (different mapping and result hashes). That alternative is a proxy
sensitivity only; it does not repair identity or become the primary result.
