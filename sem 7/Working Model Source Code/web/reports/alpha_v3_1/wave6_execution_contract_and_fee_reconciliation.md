# W6 execution contract and fee reconciliation

**Real eligible-paper lane:** `DATA_BLOCKED_NO_ELIGIBLE_STRATEGY` — 0 quotes, intents or fills.  
**Fixture lane:** `ENGINEERING_FIXTURE` — one deterministic buy fill at 10010 paise,
quantity 5, executed value 50050 paise, fees
287 paise under `fyers_standard_observed_2026_11_14`.

Actual future eligible execution must use `src/lib/research-forward-paper.ts`, which delegates to
the established atomic paper-book engine under the separate `research_v3` namespace. The Python
book is hard-blocked outside fixtures and serves only as an independent reconciliation oracle.
The runtime forward ledger uses SQLite WAL transactions (`BEGIN IMMEDIATE`, unique event IDs,
`synchronous=FULL`) and emits the required deterministic JSONL audit export.
Legacy main/practice books retain their original fee semantics. Fixture cash/holdings/no-negative
reconciliation: `True`. T+1 settlement and current-plan brokerage,
statutory charges, GST and DP-once-per-ISIN/day are tested; no fixture validates real alpha or a
historical fee schedule. The 2× figure is sensitivity on this valid fixture base only.
