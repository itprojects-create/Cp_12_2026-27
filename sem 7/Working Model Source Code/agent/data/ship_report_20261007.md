# Ship Report — NEW_PLAN execution (Day 1-6), 2026-10-07

**Tests:** 108 passed (`pytest tests/ --ignore=test_technical(live)`), incl. 5 Day1 + 5 Day2 + 5 v3 + 4 overlay + 3 Day5 new.
**Tokens:** ~0 (all builds deterministic; no eval re-runs burned).
**Contract:** additive-only (`openapi.json +18`, `schemas.json +19`, `client.ts +2`) — frontend safe.

## What shipped

| Day | Work | Files | Proof |
|---|---|---|---|
| 1 T1.1 | Fundamentals PIT: historical as_of never sees `.info` | `app/agents/analysts.py` | `test_day1_leaks.py` |
| 1 T1.2 | Events `fetched_at`+revision note; `forward_return auto_adjust=True` | `app/data/events.py`, `app/eval/run.py` | same |
| 1 T1.3 | Universe tiers + SME illiquidity gate | `app/data/universe.py` | same |
| 2 T2.1 | `PortfolioContext` + sid isolation + Trader/Risk/PM wiring | `app/portfolio.py`, `graph.py`, `trader_risk.py`, `api/v1.py` | `test_day2_scaffold.py` |
| 2 T2.2 | 5-tier + REVIEW + size map | `app/rating.py` | same |
| 2 T2.3 | Verified snapshot (source of truth) | `app/data/snapshot.py` | same |
| 2 T2.4 | `DATA_OK/UNAVAILABLE/NO_DATA` taxonomy | `app/data/base.py` | same |
| 3 | Core v3 prereg + module + backtest | `data/prereg_core_v3.md`, `app/core/trend_core_v3.py`, `scripts/run_core_backtest_v3.py` | `test_core_v3.py` + `data/core_backtest_v3.json` |
| 4 | Veto overlay + retry sandbox + prereg | `app/core/overlay.py`, `app/agents/retry_manager.py`, `data/prereg_overlay_retry.md` | `test_day4_overlay.py` |
| 5 | Alpha map + settle job + HTML report | `app/eval/alpha.py`, `scripts/settle_memory.py`, `scripts/render_report.py` | `test_day5_eval.py` |
| 6 | AngelOne read-only adapter | `app/data/broker_angel.py` | paper-log, no orders exist |

## Measured (one run each, recorded as-is)

| metric | Core v2 | Core v3 | delta |
|---|---|---|---|
| CAGR | 6.15% | 5.25% | -0.90pp (cost of safety) |
| Sharpe | 0.698 | **0.705** | +0.007 ✓ |
| MaxDD | 16.35% | **12.46%** | -3.89pp ✓ |
| Costs | 6.41% | **3.51%** | -45% |
| Switches | 3968 | **1081** | -73% |
| 2022 ret | -10.25% | **-5.43%** | halved ✓ |
| Exposure | 49.7% | 46.4% | -3.3pp |

**v3 gate (prereg):** MaxDD<16.35 OR Sharpe>0.698 AND 2022>-10.25 → **PASS all three.**
v2 file untouched. 2026 drag (-0.3%) is the known cost of the turnover filter in a flat year.

## Honestly NOT yet claimed

1. Overlay veto and retry m10 are **built + unit-tested, NOT evaluated** on the 2025H2-2026 unseen window. Prereg gates written; one-shot reads pending. LLM stays off the money path until that read passes.
2. NIFTY500/SME lists (`data/nifty500.txt`, `data/sme.txt`) not supplied — adapter raises loudly until they are. v3 backtest above is NIFTY50 for comparability.
3. Survivorship bias remains (2026 members). Disclosed in both backtest JSONs.
4. AngelOne `fetch_portfolio()` is stubbed (raises NotConfigured) — wire SmartConnect + `getHolding()` + `holdings_to_portfolio()` before paper size.
5. Working-tree note: `git status` shows pre-existing uncommitted changes outside this plan's scope (config/regime/yfinance tweaks, sessions.log growth, one eval-report deletion). Untouched by this shipment; review before commit.

## Monday demo path

1. `python scripts/render_report.py` → open `data/complete_report.html` (self-contained).
2. `python scripts/run_core_backtest_v3.py` reproduces the table (zero tokens).
3. `POST /api/v1/sessions {"portfolio": {...}, "manager_mode": "frozen"|"retry"}` — frozen default; retry isolated.
4. Frontend: pull latest `frontend-client/client.ts` (additive `portfolio?`, `manager_mode?` only).
