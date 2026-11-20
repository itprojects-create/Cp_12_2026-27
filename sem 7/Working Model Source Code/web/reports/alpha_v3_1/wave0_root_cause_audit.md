# Quant Plus V3.1 — Wave 0 execution evidence

**Date:** 2026-11-12 · **Executor:** lead engineering agent (per `QUANTPLUS_V3_1_MASTER_CODING_AGENT_PROMPT.md`)

## Verified baseline

- **Repositories/revisions:**
  - `D:\Quant-Plus` @ `36c0c96` ("Your commit message"), branch `main` — dev copy of `quantplus_intelligence` in `backend-extension/`.
  - `D:\QP\agent-service` @ `2a8b9dc` ("feat: add live intelligence and prediction service flows") — production runtime the Task Scheduler executes; the two `quantplus_intelligence` copies were byte-identical before Wave 0 changes.
- **Uncommitted local user changes (preserved, not overwritten):** `backend-extension/quantplus_intelligence/forecast/{aggregate,baselines,evidence,forecasters,jobs,schema,service}.py`, `news/google_news.py`, `tests/{test_forecast_system,test_intelligence}.py`, untracked `forecast/bridge.py`, `forecast/shadow.py`, `scripts/`, `test_forecast_bridge.py`, `test_forecast_paper.py`, `Status.md`, both V3.1 planning documents.
- **Environment:** Windows 11, Python 3.11.9, bun 1.4.4, runtime venv `D:\Quant-Plus\.local-data\backend-runtime`.
- **Source files examined:** `forecast/{ledger,service,jobs,bridge,shadow,scoring,aggregate,evidence,forecasters,inputs,schema,baselines,events}.py`, `exchange_calendar.py`, `nse_calendar.json`, `news/service.py`, `src/lib/{paper-fees,money,forecast-api}.ts`, `src/lib/paper-book/engine.test.ts`, `src/components/app/stocks/ForecastCard.tsx`, `src/lib/quant/strategy.ts`, `agent-service/scripts/register-forecast-jobs.ps1`, production `data/forecast_reports/*`.
- **Data/DB paths:** production ledger `D:\QP\agent-service\data\forecast_ledger.sqlite3` (WAL mode); V2 shadow stream `data/forecast_reports/paper_pnl.jsonl`; chain heads `ledger_heads.jsonl`; verified online backup at `reports/alpha_v3_1/backups/forecast_ledger_w0_backup.sqlite3` (sha256 `f5b21ed7…6288ab`).
- **Previous V2 state (pre-change):** chain **valid**, 608 cards, head `fc7cea45…5fc67`; 36 scored, 116 settled abstentions, 152 settled rows total; horizons 5→305 cards, 20→303; shadow registration line dated 2026-11-05 in `paper_pnl.jsonl`; quarantined `oracle_tainted_*_DO_NOT_USE.json` untouched.
- **Old test results:** 465 backend-extension tests passed before any change.

## Diagnosis

| Suspected issue | Verdict | Proof |
|---|---|---|
| Oct 30 5D cohort unsettled | **NOT_REPRODUCED** | `settlement_waterfall.json`: all 23 non-abstaining h=5 cards on 2026-10-30 are `ALREADY_SETTLED`; 23 h=20 cards are correctly `NOT_MATURE` (20 sessions after Oct 30 ≈ Nov 27). The Nov 11 settle run settled 150 (log). Status.md's "2 settled" was accurate for Nov 6–7 and is now stale, not broken. |
| 9 cards matured but unsettled | **REPRODUCED (benign)** | All 9 are `as_of=2026-11-04, h=5` maturing **today** (2026-11-12, close not yet processed). Normal operational timing; tonight's settle handles them. No backdating performed. |
| Abstention rate 76.5% (465/608) | **REPRODUCED with root causes** | `abstention_waterfall.json`: per-voter reasons from stored extras — LLM gateway "model unavailable" on ~465–468 of 607 cards (technical 465, relative 466, generalist_blind 468); events slice empty on 607/607; news empty on 470; delivery flows unavailable on 254. Aggregation requires ≥3 active votes; the two classical voters (momentum, reversal) always answer, so any run with the gateway down abstains wholesale. Recent-100 answerable: 14/100 at h=5 and 14/100 at h=20 — consistent with Status.md's 12/100 and 11/100 once the differing batch dates/versions are reconciled (103 older cards are model_version `forecast-v1`). |
| bridge/shadow label benchmark-relative excess as net P&L | **REPRODUCED** | `bridge.py:59` `long_edge = mean(excess) - 0.004`; `shadow.py:189` `net = excess - 0.004`. Fixture: stock −5% vs benchmark −6% ⇒ V2-style number reads +0.6% while the true cash P&L is **−₹5,217.30** (−5.1173%) on a ₹100,000 trade. Fixed via new versioned metrics (below); V2 formulas untouched. |
| Worker gaps (sleep/logoff) | **REPRODUCED (structural)** | `register-forecast-jobs.ps1` uses InteractiveToken (requires logon) and StartWhenAvailable/WakeToRun on a laptop; schedule logs show an interrupted settle on Nov 11. Heartbeat + missed-session detection + alert interface added (below); uptime honestly labelled `CONDITIONAL`. |
| News "neutral article" invention | **NOT_REPRODUCED** | `news/service.py:49` treats an empty answer as a successful no-news query; forecast path never fabricates an article. |

## Code changes

- **New:** `backend-extension/quantplus_intelligence/research_v3/{__init__,economics}.py` — integer-paise fee adapter mirroring `src/lib/paper-fees.ts` (`nse-cm-delivery-2026-03-01`, round-half-away-from-zero, STT-to-rupee per fill), optional date-versioned FYERS delivery brokerage `min(0.3%·value, ₹20)` per executed order, and versioned metrics `v3_benchmark_relative` / `v3_trade_cash_pnl` / `v3_net_absolute` with mandatory semantics labels.
- **New:** `backend-extension/quantplus_intelligence/forecast/heartbeat.py` — append-only heartbeat JSONL, per-job OK/MISSED/NOT_DUE_YET for the verified NSE session, `MISSED_SESSION` vs `UNMONITORED` distinction, `QP_ALERT_WEBHOOK_URL` alert route that reports `NOT_CONFIGURED` rather than assuming delivery.
- **Additive edits (existing keys/formulas unchanged):** `forecast/bridge.py` `edge_gate()` gains `metric_semantics`; `forecast/shadow.py` `summary()` gains `metric_semantics`; `forecast/jobs.py` records heartbeats in daily/settle/paper/catchup and adds the `status` verb.
- **New scripts:** `scripts/wave0_baseline.py`, `scripts/wave0_abstention_waterfall.py`, `scripts/wave0_fee_semantics.py`, `scripts/fee_parity_bun.ts`.
- **New tests:** `tests/test_research_v3_economics.py` (5), `tests/test_worker_reliability.py` (9).
- **Synced to runtime:** the four forecast files + `research_v3/` copied to `D:\QP\agent-service\quantplus_intelligence\` so the registered scheduler runs the same code.
- **Rollback:** delete the new files and revert the three additive edits (no data migration involved; ledger untouched).
- **Why reused:** the hash-chained ledger, settlement exactly-once guard, verified calendar, paise book and news honesty were already correct — extended, not forked.

## Tests actually run

| Command | Date / environment | Result | Pass/fail/skip | Notes |
|---|---|---|---|---|
| `python -m pytest tests/ -q` (backend-extension) | 2026-11-12, pre-change | `465 passed in 15.04s` | pass | baseline |
| `python -m pytest tests/ -q` (backend-extension) | 2026-11-12, post-change | `479 passed in 11.40s` | pass | 465 + 14 new |
| `bun backend-extension/scripts/fee_parity_bun.ts` | 2026-11-12 | exit 0, 6 fixtures | pass | TS book engine truth |
| `pytest ...::test_python_fee_mirror_matches_typescript_book_engine` | 2026-11-12 | pass | pass | paise-for-paise vs TS |
| `python backend-extension/scripts/wave0_fee_semantics.py` | 2026-11-12 | exit 0, `all_match: true` | pass | artifact writer |
| `python backend-extension/scripts/wave0_baseline.py` | 2026-11-12 | exit 0, chain valid | pass | backup + hashes |
| `python -B -m quantplus_intelligence.forecast.jobs status` (agent-service runtime venv) | 2026-11-12 | exit 0 | pass | `UNMONITORED`, `NOT_CONFIGURED`, `NOT_DUE_YET`, overall OK |

## Quant metrics (where market evidence exists)

- Dates/symbols: 608 cards, symbols = NIFTY 50/Next-50 universe recorded 2026-10-20 → 2026-11-11; calendar verified against NSE circulars in `nse_calendar.json` (2026 verified; Nov 10 Diwali holiday, Nov 8 Muhurat special session excluded).
- Oct 30 5D cohort: 23/23 settled; no price invented; no `recorded_at` rewritten.
- Fee truth (integer paise): ₹10k BUY 1188 / SELL 1038; ₹1L BUY 11874 / SELL 10374; round trip ₹22,248 on ₹1L (0.222%) vs ₹2,076 on ₹10k (0.208%) — size-dependent, matching the TS book engine exactly.
- Correction fixture: +1.00pp benchmark-relative vs −₹5,217.30 absolute cash.
- No profitability claim is made anywhere; V2 scoreboard remains research evidence.

## Integrity and operations

- V2 pre/post: backup head `fc7cea45…5fc67` = live head at audit time; 608 rows and 152 settlements identical; `paper_pnl.jsonl`, `ledger_heads.jsonl`, bridge snapshots hashed in `v2_pre_post_hashes.json`.
- Production ledger opened read-only (`mode=ro`) or via the online-backup API only; no WAL mid-write snapshot passed off as stable (backup is a consistent `sqlite3.backup()` copy, journal mode reset to DELETE in the copy).
- No secrets read, printed or committed; no broker endpoints touched; every new test is hermetic (tmp paths, no network, no credentials).

## Acceptance

| criterion | status | evidence |
|---|---|---|
| W0.1 baseline, backups, hashes | **PASS** | `v2_pre_post_hashes.json`, verified backup, chain valid |
| W0.2 Oct 30 cohort diagnosis | **PASS** | cohort fully settled; waterfall classifies all 608 rows; 9 waiting cards mature today |
| W0.3 abstention waterfall | **PASS** | `abstention_waterfall.json` (76.5% abstained; root causes quantified per voter) |
| W0.4 absolute P&L vs excess bug | **PASS** | `fee_semantics_and_reconciliation.json` + 5 tests + bun parity all-match |
| W0.5 worker reliability | **PARTIAL** | heartbeat/status/alerts shipped and tested; uptime remains `CONDITIONAL` (Windows laptop, InteractiveToken); alert webhook `NOT_CONFIGURED` (operator action); catchup already idempotent |
| No V2 mutation, no fake settlement | **PASS** | read-only audit; chain re-verified live |

## Next action

Smallest safe step into **W1**: stand up the PIT warehouse module (`research_v3/warehouse.py`) with the verified calendar + the existing `data/yf_cache` and `data/raw/NSE` archives as first sources, a `RETROSPECTIVE` vs contemporaneous label, and the no-lookahead/effective-membership fixtures — before any new downloader is written. The 9 cards maturing today are settled by tonight's already-scheduled settle job (no manual intervention).
