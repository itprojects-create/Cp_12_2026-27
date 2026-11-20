# W5 preflight and source-rights record

**Evidence time:** 2026-11-14T09:05:10.030883+00:00  
**Scope:** Wave 5 only; RESEARCH_ONLY; no deployment, provider call, staging or commit.

## Two-repository checkout baseline

| Checkout | Branch / HEAD | Staged | Tracked worktree changes | Untracked | Status snapshot SHA-256 |
|---|---|---:|---:|---:|---|
| Development | `main` / `36c0c960b50860596af6c25c68df3187b8d10866` | 0 | 12 | 120 | `469065863d696f3f79630e5773ee3b672d9cbce46efc9be759b6986f6c16428c` |
| Agent service | `master` / `2a8b9dca2d5657955848803bc1bbc705343988f8` | 0 | 36 | 1528 | `f023300de0f64692144168075065644e022f3a74bac7b534e0a32e8e1d7378d9` |

The complete exact pre-W5 path inventory (including all 1528 production
untracked paths) is `wave5_preflight_git_status.json`. No tracked file below was edited by W5.
The sole existing report intentionally updated later is `wave_acceptance_matrix.md`, explicitly
required by the W5 handoff; all code changes use new W5 paths.

### Development tracked user changes (preserved)

- ` M` `FORECAST_HANDOFF.md`
- ` M` `backend-extension/quantplus_intelligence/forecast/aggregate.py`
- ` M` `backend-extension/quantplus_intelligence/forecast/baselines.py`
- ` M` `backend-extension/quantplus_intelligence/forecast/evidence.py`
- ` M` `backend-extension/quantplus_intelligence/forecast/forecasters.py`
- ` M` `backend-extension/quantplus_intelligence/forecast/jobs.py`
- ` M` `backend-extension/quantplus_intelligence/forecast/schema.py`
- ` M` `backend-extension/quantplus_intelligence/forecast/service.py`
- ` M` `backend-extension/quantplus_intelligence/news/google_news.py`
- ` M` `backend-extension/tests/test_forecast_system.py`
- ` M` `backend-extension/tests/test_intelligence.py`
- ` M` `src/components/app/stocks/OrderPanel.tsx`

### Agent-service tracked user changes (preserved)

- ` M` `.env.example`
- ` M` `app/agents/_util.py`
- ` M` `app/agents/graph.py`
- ` M` `app/agents/technical.py`
- ` M` `app/api/market.py`
- ` M` `app/api/stocks.py`
- ` M` `app/api/v1.py`
- ` M` `app/config.py`
- ` M` `app/data/fyers_provider.py`
- ` M` `app/data/live_market.py`
- ` M` `app/gateway/codecraft.py`
- ` M` `app/gateway/openrouter.py`
- ` M` `app/main.py`
- ` M` `app/research/orchestrator.py`
- ` M` `contract/openapi.json`
- ` M` `data/corp_action_coverage_20261010.json`
- ` M` `data/membership_quality_20261010.json`
- ` D` `data/monthly_audit_2026-10.json`
- ` M` `data/paper_signals.jsonl`
- ` M` `data/sessions.log`
- ` M` `quantplus_intelligence/api.py`
- ` M` `quantplus_intelligence/baselines.py`
- ` M` `quantplus_intelligence/config.py`
- ` M` `quantplus_intelligence/market.py`
- ` M` `quantplus_intelligence/market_data.py`
- ` M` `quantplus_intelligence/news/google_news.py`
- ` M` `quantplus_intelligence/terminal.py`
- ` M` `quantplus_intelligence/terminal_api.py`
- ` M` `quantplus_intelligence/volume.py`
- ` M` `tests/conftest.py`
- ` M` `tests/test_fyers_integration.py`
- ` M` `tests/test_gateway_limits.py`
- ` M` `tests/test_health.py`
- ` M` `tests/test_research_grounding_boundary.py`
- ` M` `tests/test_stock_integration.py`
- ` M` `tests/test_technical.py`

## W1 warehouse verification

- Path: `D:\Quant-Plus\backend-extension\data\research_v3\warehouse.sqlite3`
- Size: **1,681,383,424 bytes**
- SHA-256: `21787a7d07fca1f5126d0c33ce3d73842f6268411624543dbf15217ce9d4e8a4`
- Open mode used by W5 analytics: SQLite URI `mode=ro` plus `PRAGMA query_only=ON`.
- Verified inventory: **5,232,265 rows / 4,675 symbols / 2,777 sessions**, 2015-01-01
  through 2026-09-17. No W5 schema or row was written to this database.
- Known W1 limitations remain: 2024-H1 and post-2026-09-17 spans, mixed
  membership knowability, and unresolved split/bonus/dividend history.

## Integration inventory and location decision

- Existing W2 contracts and hash journal: `research_v3/lab/`; W5 compiles only genuinely
  supported templates into that frozen StrategySpec rather than altering it.
- Existing W3 numerical plane: `research_v3/quantlab/`; W5 monitoring reads identities only.
- Existing W4 event/agent plane: `research_v3/events_ai/`; Mercury's frozen four-tool allowlist
  is unchanged and W5 event capture does not invoke Jev.
- W5 additive modules: `research_v3/library/`, `crisis/`, `monitor/`,
  `event_capture/`, plus `wave5.py` read-only adapter.
- Existing application surfaces were inspected: forecast ledger, Strategy Lab, Research
  Network, Ripple map, Portfolio X-ray/exposure, risk centre, Review Hub and scheduled
  forecast worker. W5 neither replaces Ripple's graph nor creates a second account/portfolio ledger.
- Database-first integration is used. No UI, paper/order endpoint, balance, risk policy or
  broker pathway is changed.

## Source and rights status

| Source | Use in W5 | Rights/access conclusion |
|---|---|---|
| W1 official NSE bhavcopy archive | Retrospective raw-price crisis observations | Existing manifest says personal-research use; archive was captured 2026-09-18, so old periods stay `HISTORICAL_RETROSPECTIVE` |
| NIFTY 50 TRI local history | Context benchmark only | Official-index history; not redistributed; basis mismatches raw holding prices |
| RBI Financial Stability Report, July 2020 | COVID/panic-selloff context | Official report page `ID=1153` and Chapter I `ID=1147` resolved on 2026-11-14; exact operational boundaries separately cross-checked and present in local official observations |
| NSE corporate XBRL/announcements page | Forward connector discovery | Public entry point is **not** blanket crawler/storage permission; page and terms fetches timed out; automated capture rights remain unapproved |
| NSE corporate actions page | Discovery only | Access/redistribution permission unverified; no action history invented or imported |
| Existing service `data/raw/NSE` files | Inventory only | Pre-W5 user data with capture/right lineage not certified for W5; not imported and not called contemporary evidence |

Forward collector status is `NOT_CONFIGURED`; legal/terms review and an approved documented
export/feed are required before enabling it. External network is disabled in W5 tests. The
previous chat-exposed provider key still requires operator rotation; W5 never reads or calls it.

## Baseline commands

- Development full: `cd backend-extension && python -m pytest tests/ -q` → `651 passed in 41.15s`.
- W1-W4 research subset: development `177 passed in 26.71s`; service `171 passed, 1 skipped in 27.17s`.
- Service offline-safe full baseline: `python -m pytest tests/ -q -p w5_offline_pytest_plugin`
  → `5 failed, 670 passed, 2 skipped in 304.66s`; one explicit skip prevents the live-provider
  test from making a network call. The five reproduced failures exactly match W4's persistent
  provider-precedence/configuration failures.

Missing or inaccessible evidence is labelled `UNVERIFIED`/`NOT_CONFIGURED`; it is not inferred.
