# Quant Plus: Final-Submission Paper-Trading Demonstration

> **DEMO TRADE. This is not a forward-study result.** One simulated order was placed in an isolated
> ₹1,00,000 virtual account `demo:final-submission-2026-11-20`, using the existing deterministic
> TypeScript paper-book engine. It is **not** part of the V2 forecast ledger or the V3.1 forward
> study. No broker order was submitted. **Brokerage is assumed to be ₹0 (`BROKER_ASSUMPTION`) and
> has not been checked against the operator's FYERS account.**

**Date:** Friday 20 November 2026, 14:05 IST (NSE session verified open, calendar `nse-cm-2026.2`)
**Outcome:** `LIVE_PAPER_DEMO_EXECUTED`. All 11 validation checks passed, so the offline-fixture fallback was not needed.

## How the prerequisites were decided

| Prerequisite | State | Decision |
|---|---|---|
| Server-observed live quote | FYERS connected (token valid to 21 Nov 06:00 IST); quote passed the app's `LIVE` execution policy | Used |
| Fee schedule | The V3.1 FYERS-plan gate is `DATA_BLOCKED / OPERATOR_ACCOUNT_PLAN_NOT_CONFIRMED` | The operator chose the app's default `nse-cm-delivery-2026-03-01` schedule. Brokerage is a disclosed ₹0 assumption, and the V3.1 gate stays blocked |
| Isolation | New in-memory book with no `research_forward` config. Output is written only to this folder | Used |

## What happened

| Step | Result |
|---|---|
| Quote (FYERS, open, not delayed, not stale) | TCS last ₹2,376.80 · bid ₹2,376.60 × 45 · ask ₹2,376.70 × 39 · provider time 14:05:06 IST |
| Risk-guard probe (on a discarded copy of the book) | BUY 20 TCS (about ₹47.5k) was **rejected** with `POSITION_VALUE_LIMIT`, because the limit is 25% of equity |
| Order | MARKET BUY 10 TCS, DELIVERY/DAY, stop ₹2,305.40 (−3%) and target ₹2,495.55 (+5%). These are demo parameters, not an AI signal |
| Fill | 10/10 **FILLED** at the ask, ₹2,376.70 (`QUOTE_BID_ASK`, 0 bps slippage). Executed value ₹23,767.00 |
| Charges | STT ₹24.00 · exchange ₹0.73 · SEBI ₹0.02 · stamp ₹3.57 · GST ₹0.14 · **brokerage ₹0.00 (assumption)**. **Total ₹28.46**, which matches the pre-trade estimate |
| Cash ledger | Deposit +₹1,00,000.00 → BUY −₹23,767.00 → charges −₹28.46 → **cash ₹76,204.54** (₹0 reserved) |
| Position | 10 TCS, average ₹2,376.70, 0 settled / 10 unsettled (T+1 due 24 Nov 00:00 IST), mark fresh |
| Protection | Stop/target protection is `ACTIVE` on 10 shares |
| NAV | ₹76,204.54 + 10 × ₹2,376.80 = **₹99,972.54**. The −₹27.46 change is −₹28.46 charges plus ₹1.00 mark-to-market. This is **not profit and not a performance claim** |
| Audit trail | `RISK_DAY_ANCHORED → WALLET_DEPOSIT → ORDER_ACCEPTED → PROTECTION_CREATED → ORDER_FILLED`, with unique monotonic sequence numbers |
| Reconciliation | PASS after the fill and after the mark: cash = ledger, positions = fills, charges and deposits reconcile |

The second quote fetch for the NAV mark returned the same provider tick as the fill quote. No price
was invented.

## DEMO trades vs genuine forward-study trades

| | This demo | V2 forecast ledger / V3.1 forward study |
|---|---|---|
| Account | `demo:final-submission-2026-11-20`, isolated | Main/hosted book; `research_v3` namespace |
| Purpose | Show engine mechanics | Pre-registered evidence |
| Signal | None (manual demo order) | Only through gates. The V2 bridge is HALT, and V3.1 is `DATA_BLOCKED_NO_ELIGIBLE_STRATEGY` |
| Fees | App default, brokerage assumed ₹0 | V3.1 FYERS plan, still unconfirmed |
| Counts toward results | **No** | Yes, once matured |

## Preservation

These files have identical SHA-256 hashes before and after the demo, and again after the regression
runs: `.local-data/workspace.json`, the Wave 6 fixture, signal/paper ledgers and NAV report,
`forecast_reports/ledger_heads.jsonl`, `paper_pnl.jsonl`, `research_v3/warehouse.sqlite3`,
`paper-book/engine.ts` and `paper-fees.ts`. No application code was changed. Nothing was written
to the main, practice or hosted (InsForge) books.

## Regression results (20 Nov 2026)

| Suite | Result |
|---|---|
| `npm test` (125 node tests + 21 script suites) | **PASS**: 125/125, all script suites passed |
| `npm run typecheck` | **PASS** |
| `npm run test:intelligence` (pytest) | **PASS**: 789 passed |
| `npm run lint` | **FAIL**: 26 Prettier formatting errors, all in existing uncommitted V3.1 files (`src/lib/paper-fees.ts`, `src/lib/research-forward-paper.ts`, `src/lib/research-forward-paper.test.ts`, `backend-extension/scripts/fee_parity_bun.ts`). Left untouched because they are unrelated to this demo. The demo folder lints clean |

## Files

- `run-live-demo.ts`: the demo runner. It fails closed and refuses to run a second time.
- `render-report.mjs`: builds `report.html` and the screenshots.
- `demo-result.json`, `demo-book.json`: full engine output and book state.
- `screenshots/00-full-report.png` … `10-isolation.png`: each shot includes the DEMO banner.
- `regression-*.log`: test output.
