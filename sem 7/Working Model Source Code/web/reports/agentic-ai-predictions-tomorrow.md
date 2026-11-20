# Quant Plus — Agentic AI prediction brief

> **Presentation status:** frozen forward forecast snapshot. Current outcomes are pending settlement.

- Generated UTC: `2026-11-03T13:56:56.555136+00:00`
- Latest completed cutoff: `2026-11-02T00:00:00+00:00`
- Model: `forecast-v2-horizon-gated`
- Target: probability that a stock outperforms NIFTY 50 over the stated trading-session horizon.

## What can be shown tomorrow

The latest batch contains the model's point-in-time forecast cards, ranked probability leans, risk estimates, and explicit abstentions. These are valid predictions to demonstrate, but they are not yet accuracy results because their forward horizons have not completed.

| Horizon | Cards | Answerable | Abstained | Maturity |
|---:|---:|---:|---:|---|
| 5 sessions | 100 | 12 | 88 | 2026-11-09 |
| 20 sessions | 100 | 11 | 89 | 2026-12-02 |

Across the full ledger there are **303 locked cards**, **2 settled outcomes**, and **1 scored non-abstaining forecasts**. Any current accuracy figure is provisional until a meaningful settled sample exists.

## Strongest current probability leans

These are model rankings for demonstration, not trade instructions.

| Horizon | Symbol | P(outperform) | Class | Matures | Vol forecast | Disagreement |
|---:|---|---:|---|---|---:|---:|
| 5 | APOLLOHOSP | 42.00% | Underperform lean | 2026-11-09 | 4.17% | 6.94% |
| 5 | AXISBANK | 44.90% | Underperform lean | 2026-11-09 | 2.90% | 6.13% |
| 5 | ADANIENT | 55.00% | Outperform lean | 2026-11-09 | 4.51% | 4.03% |
| 5 | BAJFINANCE | 55.00% | Outperform lean | 2026-11-09 | 3.20% | 3.34% |
| 5 | BAJAJFINSV | 45.89% | No clear edge | 2026-11-09 | 1.90% | 5.73% |
| 20 | BAJAJFINSV | 42.00% | Underperform lean | 2026-12-02 | 3.79% | 6.97% |
| 20 | ADANIPORTS | 57.16% | Outperform lean | 2026-12-02 | 8.98% | 3.76% |
| 20 | ADANIENT | 43.00% | Underperform lean | 2026-12-02 | 9.02% | 7.37% |
| 20 | BHARTIARTL | 57.00% | Outperform lean | 2026-12-02 | 5.76% | 6.65% |
| 20 | BSE | 56.00% | Outperform lean | 2026-12-02 | 8.75% | 5.28% |

## Historical result to disclose

The archived forward evaluations contain **11 reports**. Agent accuracy ranged from **5.9% to 50.0%** with a descriptive mean of **27.2%**. **0/11** beat the best constant baseline.

These archived configurations are separate from the current `forecast-v2-horizon-gated` forward ledger and must not be presented as current live accuracy.

## Suggested 5-minute demonstration

1. Open the `Tomorrow Brief` tab in `agentic-ai-predictions.xlsx`.
2. Show the latest cutoff, the two horizons, and why the system abstains on many cards.
3. Open `Predictions` and inspect one high-probability lean, its model version, risk estimate, maturity date, and ledger hash.
4. Open `Votes` to show classical momentum/reversal anchors and the separate forecaster inputs.
5. Finish with the `Settled Results` and `Diagnostics` tabs: explain that settlement is forward-only and the trade bridge remains HALT until evidence accumulates.

## Answer if asked for accuracy

> We have a working, auditable forward forecast ledger, but the current v2 sample has not matured enough to claim predictive accuracy. We show the live predictions now, preserve abstentions, and score them only after the defined 5-session or 20-session horizon. Earlier archived tests did not beat their constant baselines, so we do not claim a proven edge.

Source workbook: `reports/agentic-ai-predictions.xlsx`.
