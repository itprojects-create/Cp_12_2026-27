# Forecast system implementation — handoff log

Design: `research_notes/Agentic Recommendation Redesign/blueprint.md` (10 moves).
Code: `backend-extension/quantplus_intelligence/forecast/` (pure Python, no new deps).
Tests: `backend-extension/tests/test_forecast_*.py`.
Run tests: `cd D:\Quant-Plus\backend-extension; D:\Quant-Plus\.local-data\backend-runtime\Scripts\python.exe -B -m pytest tests/test_forecast_*.py -q -p no:cacheprovider`

Rules followed: numbers in code, LLM only via injected callables (tests are offline),
RESEARCH_ONLY, forward-only scoring, no Supabase, no deployment, no commits.

## Status (updated after each step)

| # | Move | Module | Status |
|---|------|--------|--------|
| 1 | Forecast Cards + proper scoring | `schema.py`, `scoring.py`, `baselines.py` | done, tested |
| 2 | Listwise sector tournaments | `tournament.py` | done, tested |
| 3 | Disclosure event library + concall diffs | `events.py`, `textdiff.py` | done, tested |
| 4 | Silicon crowd forecasters + aggregation | `forecasters.py`, `aggregate.py` | done, tested |
| 5 | Blindfold protocol | `evidence.py` | done, tested |
| 6 | Risk-first (vol + conformal ranges) | `risk.py`, `calibration.py` | done, tested |
| 7 | Meta-labeling on core | `metalabel.py` | done, tested |
| 8 | Executable falsifiers | `falsifiers.py` | done, tested |
| 9 | Personal fit layer | `personal.py` | done, tested |
| 10 | Hash-chained proof ledger | `ledger.py` | done, tested |
| W | Wildcards: robustness, disagreement | `robustness.py` | done, tested |
| S | Service + API routes | `service.py`, `forecast_api.py`, `api.py` | done, tested |
| F | Frontend Forecast Card on stock page | `ForecastCard.tsx`, `forecast-api.ts`, routes | done, typecheck+build pass |

## Log
- 2026-10-20: all 10 moves + wildcards implemented in `forecast/` and composed in `service.py`.
  `tests/test_forecast_system.py`: 22 passed (hermetic, offline, fake LLM callables).
- Backend routes (under /api/v1, website key): GET/POST `stocks/{sym}/forecast?horizon=5|20`,
  GET `forecast/scoreboard`, POST `forecast/settle` (operator only, NOT proxied). 24 tests pass.
  Ledger file: env `FORECAST_LEDGER_PATH` (default `data/forecast_ledger.sqlite3` in backend cwd).
- Frontend: `src/components/app/stocks/ForecastCard.tsx` (shown above AgentPrediction in
  `StockDetail.tsx`), `src/lib/forecast-api.ts`, new route `src/routes/api/forecast/$.ts`,
  POST added to `src/routes/api/stocks/$.ts`, proxy allowlist in `src/routes/api/agent/$.ts`
  (GET/POST `stocks/{sym}/forecast`, GET `forecast/scoreboard`; settle is NOT browser-reachable).
- Verified: 340/340 backend-extension tests, `tsc --noEmit`, eslint on changed files,
  `node scripts/test-agent-proxy.mjs`, `npm run build`. Extension installed into
  `D:\QP\agent-service` with `scripts/install-intelligence-backend.py`; app imports and
  registers `/api/v1/stocks/{stock}/forecast`, `/api/v1/forecast/scoreboard`, `/api/v1/forecast/settle`.
- NOT done: backend process not restarted; no live end-to-end forecast generated (would bill
  ~6 model calls per stock). No commits made.

## What each move does today vs what is still unwired

| Move | Working now | Still to wire (next steps) |
|---|---|---|
| 1 Forecast Card + scoring | Card schema, Brier/log-loss/CRPS/skill/reliability/coverage, scoreboard API, UI | Track Record page section showing reliability + coverage curves from `/api/forecast/scoreboard` |
| 2 Tournaments | `tournament.run` + Plackett-Luce + `llm_ranker` + `daily_ic` | Daily job: per sector (catalog `stock_catalog()` sector), build blind blocks with `evidence.render`, rank, store strengths; settle daily IC; API + UI "sector rank" |
| 3 Event library | `events.classify`, PIT `in_window`, `study`, `admit` (Bonferroni-style bar), `event_prior`; `textdiff.diff` + grounded `labelled_changes` | Feed real announcements (backend `app/data_acquisition` NSE/BSE collectors are NOT_COLLECTED) into `events=` of `service.build`; transcripts source for diffs; run forward event studies |
| 4 Silicon crowd | 6 LLM diets + momentum/reversal baselines, strict parse, track-record weights, debias, extremize | API passes no headlines/flows yet, so `news` and `flows` forecasters abstain. Wire `news_service.stock_news` headlines and delivery/flows into `forecast_api._generate` |
| 5 Blindfold | Blind render (name/date scrub, no ticker); `robustness.memorisation_gap` | Script to run named vs blind on a sample and report gaps |
| 6 Risk-first | EWMA vol, quantiles, conformal margin (auto after 30 settled), drawdown, event shock | Benchmark vs India VIX/GARCH once settled data exists |
| 7 Meta-label | `MetaLabeler` (down-only, refuses <50 labels), `compare` holdout | Feed forward-settled core trades from backend `app/forward` records; promotion via existing G1–G5 gates |
| 8 Falsifiers | Safe DSL, `evaluate`, `defaults`; rules shown on card | Live watcher: evaluate each open card's falsifiers on fresh quotes (FYERS stream) and show HEALTHY/WEAKENED/BROKEN + notify |
| 9 Personal fit | `personal.fit` + `behaviour_flags` | Route that accepts paper book (from `.local-data/workspace.json` via frontend server) and UI "What this means for you" |
| 10 Proof ledger | Hash chain, lock-before-outcome, exactly-once settle, verify, scoreboard | Schedule `POST /api/v1/forecast/settle` daily after close (backend `scripts/run_job.py` / schtasks); optional daily public head hash |
| W Wildcards | leave-one-out robustness (on card), memorisation gap, narrative crowding | Pre-register crowding→volatility test |
| Batch | — | Daily forward run over NIFTY 100 (loop `_generate` with pacing; respect day token cap) so the 45-session IC gate can be measured |

## To run / continue
1. Restart backend: `cd D:\QP\agent-service; D:\Quant-Plus\.local-data\backend-runtime\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. Frontend: `npm.cmd run dev -- --host 127.0.0.1 --port 8080 --strictPort`, open `/app/stocks/RELIANCE`, press "Generate forecast".
3. Tests: see top of this file; plus `npx tsc --noEmit`, `node scripts/test-agent-proxy.mjs`, `npm run build`.
4. After edits to `backend-extension`, reinstall: `python -B scripts/install-intelligence-backend.py --backend D:\QP\agent-service`, then restart backend.
- Fix: proxy timeout for POST `stocks/{sym}/forecast` raised 20s -> 180s (`src/routes/api/agent/$.ts`);
  ForecastCard re-reads ledger after a failed generate. First live card locked: ADANIENT 5D, p=0.46,
  ~5.4k tokens; news/events/flows forecasters abstained (feeds not wired).
- Phase 2 wiring (backend, tested 27/27): `forecast/inputs.py` (PIT headlines, NSE announcement
  events, results surprise/scheduled, delivery flows; cutoff = last bar's session close),
  `service.generate_live/live_snapshot/status/personal_view/provider_fetch`, ledger side tables
  (`forecast_extras`, `forecast_tournaments`) + tournament IC gate in scoreboard,
  `forecast/jobs.py` CLI (daily, tournament, settle, blind-gap, risk-bench, metalabel, crowding),
  routes GET `stocks/{s}/forecast/status`, POST `stocks/{s}/forecast/personal`.

## Phase 2 completion (2026-10-20) — supersedes the "still to wire" table above

Frontend: `ForecastPanels.tsx` (sector rank, evidence sources/events, crowding, live tripwires,
personal fit with conservative/balanced/aggressive profile stored in localStorage),
`pages/ForecastLedgerSection.tsx` on the Track Record page (Brier skill, log-loss, CRPS, 80% coverage,
calibration table, coverage curve, per-forecaster skill, tournament IC gate, chain status).
Proxy: GET `stocks/{s}/forecast/status` (180s), POST `stocks/{s}/forecast/personal` (only path that
forwards a JSON body, capped at 200 KB). Ledger: WAL + 30s busy timeout (shared by backend and jobs).
Scheduler: `scripts/register-forecast-jobs.ps1` (NOT run; registers settle 16:15, daily 16:30,
tournament 17:30 weekdays).

Verified: 343/343 backend-extension tests; tsc, eslint, proxy test, `npm run build` pass.
Live: `jobs settle|risk-bench|metalabel|crowding` ran (all INSUFFICIENT — no settled data yet,
ledger chain valid); `jobs daily --limit 1` locked ADANIENT 20D (p=0.47) with delivery flows
answering; 5D card reused. ADANIENT had 0 news articles (provider fine; RELIANCE has 17).

| Item | State |
|---|---|
| Daily batch, settlement, tournaments | Done as jobs; need scheduling (run the .ps1) |
| News/flows/events into crowd | Done (`inputs.py`); news only counts headlines before last close |
| Tournaments + sector rank UI | Done; first data after first `tournament` run |
| Event library | Live NSE announcement titles + results surprise/scheduled feed the events slice; forward event studies (`events.study/admit`) still need settled event outcomes — no job yet computes per-event abnormal returns |
| Concall diffs | `textdiff` ready; NO transcript source exists — needs a provider before wiring |
| Blindfold report | `jobs blind-gap` (costs ~2 crowds per symbol) — not run yet |
| Risk bench | `jobs risk-bench` — needs ≥30 settled cards |
| Meta-label | `jobs metalabel` — needs ≥50 settled core forward decisions; backend forward ledger currently has 0 matured rows |
| Tripwires live | Done (status route + UI, 10-min refresh); no push notifications |
| Personal fit | Done (route + UI); other holdings' volatility approximated at 2%/day |
| Proof ledger | Done; daily head appended to `data/forecast_reports/ledger_heads.jsonl` by `settle` |
| Crowding test | Pre-registered in `jobs.CROWDING_PREREG`; runs when ≥30 cards per group settle |

Genuinely remaining: (1) run `scripts/register-forecast-jobs.ps1` (user decision: recurring token
spend); (2) restart backend to load the new status/personal routes; (3) per-event abnormal-return job
feeding `events.study`; (4) a transcript source for concall diffs; (5) optional notifications when a
tripwire turns BROKEN; (6) browser e2e test for the card (not written).
- Added `jobs event-study` (forward abnormal returns per disclosure type from events first seen by
  cards → `events.study/admit`; report in data/forecast_reports). 344/344 tests. Item (3) above is DONE;
  add `event-study` to the weekly schedule once cards carry events.

## Forward clock live (2026-11-01) — Mercury cutover + profitability bridge

| Item | State |
|---|---|
| Provider cutover | `INCEPTION_API_KEY` (Mercury-3) added to `D:\QP\agent-service\.env`; `app/config.py` gains an `inception` provider with top precedence (Inception > Experiential > OpenRouter > CodeCraft), temperature 0.7 per Mercury-3's documented 0.5–1.0 range; `app/gateway/codecraft.py` seeds the body-policy catalog probe and persists quota days for the new provider. `DAILY_REQUEST_CAP` raised 300→3000. |
| Smoke tests | Raw SDK + gateway JSON path passed (~10 tokens). Mercury-3 spent 31 of a 32-token budget on its reasoning channel with empty content at `max_tokens=32`; the gateway's 8192 budget makes this a non-issue. |
| First settlements ever | `jobs settle` recorded ADANIENT 5D excess −5.69% (outperformed=0) and the abstaining ADANIPORTS 5D (+5.87%); chain valid. |
| First full batch | `jobs daily` on the NIFTY-50 catalog: 94 locked + 6 reused = 100 cards, 0 failed. 6/8 forecaster slices voted on every card; news/tags abstained where Google News yielded 0–1 articles (honest missingness). 5D/20D p values came out near-identical — horizon sensitivity is weak and flagged for prompt work. |
| First tournament | 37 names ranked across 7 usable sectors (day 2026-10-30, H5). Small sectors skipped by design. Tournament IC gate PENDING (needs settled days). |
| Profitability bridge | New `forecast/bridge.py` + `jobs bridge`: edge gate per horizon from settled rows only (HALT→WATCH→TRADE; bullish-slice hit rate above 0.5 and cleared 0.4% round-trip cost hurdle), half-Kelly-capped sizes (cap 10×2×(p−0.5)×0.5), RESEARCH_ONLY order intents. First run: HALT (1 scored of 30), 47 above-threshold cards correctly skipped, artifact in `data/forecast_reports/bridge/`. |
| Tests | `tests/test_forecast_bridge.py` (4 hermetic tests) added; forecast suite 32/32 pass (`test_forecast_bridge.py` + `test_forecast_system.py`). Extension installed into the backend via `scripts/install-intelligence-backend.py`. |
| Schedule | `D:\QP\agent-service\scripts\register-forecast-jobs.ps1` created AND executed: `QPForecastSettle` 16:15, `QPForecastDaily` 16:30, `QPForecastTournament` 17:30 IST weekdays (schtasks verified). Item (1) in "Genuinely remaining" is DONE. |
| Seriously remaining | Backend uvicorn still down (status/personal routes unloaded; run when UI views are wanted — the warm worker will spend tokens once up). Concall transcript source still missing. Bridge stays HALT until ~30 settled per horizon (first big settle Fri 2026-11-06). |

## Acceleration pass (2026-11-01, later) — wider universe, news window, horizon conditioning

| Change | Detail |
|---|---|
| Universe widened 50→100 | `scripts/update_forecast_universe.py` fetches the official NSE constituent CSVs (`ind_nifty50list.csv`, `ind_niftynext50list.csv`) and writes `data/forecast_universe.json` (provenance: retrieved_at, index, industry). 100 symbols, 0 failures, 17 industries — 9 sectors have tournament-block depth (Financial Services 23, Capital Goods 11, Auto 9, Metals 8, Healthcare 8, FMCG 7, Oil&Gas 6, IT 6, Power 6). `jobs.universe()` reads this file first (env `FORECAST_UNIVERSE_FILE` override), keeping the market-data feed, warm-list and stock_catalog fallbacks behind it, deduped preserving order. |
| News search window | `google_news.py` searched `when:1d` while the age filter keeps 48h — fresh-at-cutoff headlines were provider-excluded. Search window is now `max(1, ceil(max_article_age_hours/24))d`, i.e. `when:2d`, matching the filter. Regression test asserts the relationship, not a literal (`test_intelligence.py` patched per the audit's convert-defect-tests rule). |
| Horizon conditioning | `forecasters.SYSTEM` now carries explicit horizon discipline text (5-session vs 20-session drivers, and 'an answer identical across horizons is wrong'); `evidence.render` gained an optional `horizon` kw that prefixes `horizon=N sessions` in the evidence head; `run_forecaster` passes it. Live probe (read-only, no card locks): H5 mean 0.547 vs H20 0.570, with per-forecaster movement (relative 0.53→0.60). Cards already locked today (100, as_of the Oct 30 bar) are unaffected and unchanged — reuses stay keyed on (symbol, horizon, bar). |
| Verification | Full extension suite 454/454 pass. Extension reinstalled into `D:\QP\agent-service` — tomorrow's scheduled jobs run this code. |
| Cost projection | Daily batch now ~2× tokens (~200 cards/day): roughly $0.30–0.60/session on Mercury-3 launch pricing, still far under the old Experiential/Labs credit burn. |

## Scheduler self-correction (2026-11-03) — missed Monday + intraday veto

| Item | Detail |
|---|---|
| Monday's session missed | All three tasks reported `0x800710E0` at 19:02 with zero cards for Nov 2 (ledger histogram confirms). Two causes: the registration script's `.Split("QPForecast")` — PowerShell splits per *character*, yielding an EMPTY job verb in every task action — and machine unavailability/battery conditions at task time. Nov 2 is unrecoverable under forward-only discipline (no backfill below the PIT line); Oct 30 cards still settle Friday. |
| Task actions fixed | `register-forecast-jobs.ps1` rewritten with an explicit name→verb map and rebuilt via `Register-ScheduledTask`; XML verified: `settle`/`daily`/`tournament` verbs now appear in all three action lines. Settings: StartWhenAvailable, WakeToRun, battery-run allowed, no battery stop, 6h limit, IgnoreNew. Live proof: manual `/Run` of QPForecastDaily mid-session printed the veto JSON into `schedule_daily.log`. |
| Intraday veto (audit AI-01) | New `service.session_running()` (IST clock, 09:15–15:35, weekdays). `service.generate_live` now raises before touching any provider during a live session (protects the browser route too); `jobs.daily` and `jobs.run_tournament` early-return with a `skipped` reason and zero token spend. `settle` stays anytime-safe (completed closes only). Mid-session live test: `jobs daily --limit 2` → skipped, 0 cards, 0 tokens. |
| Tests | 3 new hermetic tests (`session_running` UTC-boundary/weekend matrix, `generate_live` refusal leaving an empty chain, jobs early-return via patched clock); full suite 457/457; extension reinstalled. |
| Today | 16:15/16:30/17:30 will run the Nov 3 bar — guard proves safe because a scheduled run can never fire intraday again even if the machine wakes late (e.g. a 12:00 wake would now be REFUSED by the veto instead of poisoning cards). |

## Forecast stability pass (2026-11-03)

The classical momentum and reversal votes now receive the requested 5-session or
20-session horizon. Their evidence includes 60-session relative return and trend
consistency where enough point-in-time bars exist, so a slow forecast no longer
silently reuses a short-horizon signal. Unproven LLM probabilities are bounded to
0.35–0.65 during aggregation until that forecaster has 30 forward-settled labels;
raw model output remains retained for audit. The forecast model version is now
`forecast-v2-horizon-gated`.

Verification: `pytest tests -q` → 459 passed. This improves horizon discipline and
calibration safeguards; it does not establish live predictive accuracy before the
forward ledger has a meaningful settled sample.

## Verification closure (2026-11-03)

The existing frontend formatting failure in `src/components/app/stocks/OrderPanel.tsx`
was corrected. The provider health regression in the installed backend test now
asserts the configured provider/model instead of the retired OpenRouter constant.
`npm test`, `npm run lint`, `npm run typecheck`, `npm run build`, the extension suite,
the hermetic backend suite (504 passed), and the focused prediction suite (82 passed)
all pass. The local agent service is running on `127.0.0.1:8000` with prediction
warming and the intelligence scheduler disabled, so no model calls are spent merely
by restarting it.

Browser verification completed in bounded groups because the 189-case suite exceeds
the command timeout when run as one process: all 189 cases passed across the full
coverage, intelligence, workflow, visual and workspace set. Expected Vite route and
preload warnings were non-failing.

## Evidence pass (2026-11-03, evening)

The scheduled daily batch is healthy: 200 cards were locked for the 100-symbol
universe, with no failures. Settlement ran against the current forward clock and
added 0 outcomes; the hash chain remains valid across 303 cards. Current maturity
groups are 50 cards on Nov 6, 100 on Nov 9, 50 on Dec 1, and 100 on Dec 2.

Diagnostics completed: risk benchmark `INSUFFICIENT` at 2 settled outcomes,
meta-label `INSUFFICIENT` at 0 joined labels, event study with 0 events, crowding
`INSUFFICIENT`, and an 8-symbol blind-gap diagnostic with mean gap 0.01 and no
suspect forecaster. The bridge remains `HALT` with 1 scored 5-session card and 29
more settled cards needed before its gate can end.

Tournament coverage is persisted for 5-session rankings (96 rows, 2 days, 8
sectors) and 20-session rankings (59 rows, 1 day, 5 sectors); remaining sectors
need reliable provider responses and more forward days for the IC gate. The current
export is `reports/agentic-ai-predictions.xlsx`, including a Diagnostics tab.

## Presentation package (2026-11-03)

Because the latest 5-session and 20-session cards have not matured, a tomorrow-ready
brief was generated without converting open forecasts into fake results. The latest
completed cutoff is 2026-11-02. Its 200-card snapshot contains 12 answerable and 88
abstaining 5-session cards, plus 11 answerable and 89 abstaining 20-session cards;
the current cards mature on 2026-11-09 and 2026-12-02 respectively.

`reports/agentic-ai-predictions.xlsx` now has a `Tomorrow Brief` tab with the strongest
current probability leans, maturity dates, risk fields, abstention counts, and the
archived historical comparison. `reports/agentic-ai-predictions-tomorrow.md` is the
short speaking brief and includes the exact answer for questions about accuracy.

## Profitability path, catch-up task and pre-registered paper P&L (2026-11-05)

Answered the operator's profit question honestly: realized money P&L is ?0 because
the profitability bridge (`quantplus_intelligence.forecast.bridge`) is in HALT by
design � the whole ledger had 2 settled outcomes, and the gate needs =30 settled
cards per horizon, =10 bullish, hit rate >0.5 and a mean excess clearing the 0.4%
round-trip cost hurdle before any intent exists. Nothing was weakened to fake a
profitable result.

Two approved moves were implemented to fill the evidence tank faster and to build
the profitable case without touching the gate:

### Evening catch-up task

`QPForecastCatchup` is registered in Windows Task Scheduler for Mon�Fri 21:00 IST
(`scripts/register-forecast-jobs.ps1`), chaining `daily ? settle ? paper` through a
new compound `catchup` verb in `quantplus_intelligence.forecast.jobs`. Every stage
is idempotent (cards dedupe by card_id, settlements fill matured cards only, and no
run backfills history), so a missed 16:15/16:30 batch no longer leaks the evening's
evidence � the gap that cost three runs this week (Mon Nov 2 machine unavailable,
Wed Nov 4 no completed run, Thu Nov 5 fired late and was killed). The paper verb
writes `data/forecast_reports/paper_pnl.jsonl` plus a dated snapshot
`paper_<date>.json`. The source, tests and install copy are in sync
(`backend-extension/.../forecast/jobs.py`, `tests/test_forecast_paper.py`, reinstalled
into `D:\QP\agent-service`).

### Pre-registered shadow paper-P&L stream (SHADOW)

`quantplus_intelligence.forecast.shadow` pre-registers a fixed rule with a timestamp
in the JSONL's first line: from each morning's newest post-registration batch, per
horizon (5 and 20 sessions), the top-3 bullish cards (answerable, p > 0.5;
tie-break |p-0.5| desc, p desc, symbol asc) are carried to their own horizon and
scored `net = realized excess - 0.004` strictly from the main ledger's forward
settlements. Registered 2026-11-05 14:02 UTC (19:32 IST) BEFORE any
post-registration card existed, so Batch A (locked Nov 1) and Batch B (locked
Nov 3) are excluded forever under the rule; picks begin with the first batch locked
after registration. It creates no intents, spends no tokens, opens nothing: the
bridge's `edge_gate` remains the only path to order intents. Hermetic coverage:
registration idempotence, exclusion of pre-registration batches, deterministic
top-3 picks, idempotent re-pick, net-of-cost settlement, and summary math
(43 passed across the focused forecast suites).

`reports/agentic-ai-week-results.xlsx` now carries a `Paper P&L` tab built from the
JSONL (registration + honest empty state at 0 picks) and the Jobs Log records both
today's registration and the new catch-up task. First post-registration batch is
expected from tonight's 21:00 catch-up; Batch A 5D settles Fri Nov 6 and Batch B 5D
Mon Nov 9, so the first shadow score lines follow then. Forward-only: anything on
this stream is paper evidence for the gate, not money P&L.

## Friday Nov 6 flatline — Batch D lost to sleep; workbook shipped; research deliverable (2026-11-07)

| Item | Detail |
|---|---|
| Machine unavailable (again) | 5 of 6 scheduled evening runs this week were lost to machine sleep/shutdown. Fri: settle fired on the 18:24 wake and completed clean (0 matured, chain OK, 320 cards); daily fired 18:24 and was terminated C000013A mid-news-analysis — 0 cards; tournament killed the same way; the 21:00 catch-up fired 21:41 (late wake), reached BAJAJFINSV's news analysis and died — 0 cards. |
| Ledger state | 320 cards: Batch A (Oct-30 cut, 100), Batch B (Nov-2 cut, 200), Batch C (Nov-4 cut, 17 partial). No Batch D — the Nov 5 cutoff never locked and is unrecoverable under forward-only discipline. `paper_pnl.jsonl` holds only the registration line; 0 picks by design until a complete post-registration batch locks. |
| Evening watcher | `scripts/evening-refresh.py` armed at 11:55, slept with the machine, woke 18:24 after its 17:25 deadline, correctly skipped picks (batch_complete: false), regenerated `reports/agentic-ai-week-results.xlsx` (rc=0): 317 cards priced through Nov 5, Batch C in, Paper tab honest-empty, cross-checks pass (WIPRO Nov 3 = 198.0, ADANIENT Nov 5 = 2733.30). Status JSON: `reports/evening-refresh-status.json`. Note: the watcher's hardcoded BATCH_AS_OF / window must be parameterized before reuse. |
| Upstream data gap | Yahoo's BAJAJ-AUTO.NS daily series omits the Nov 5 row (jumps Nov 4 → Nov 6) — its 2 Batch C cards honestly show "Pending price data"; nothing was filled in. |
| Settlements ahead | Batch A 5-session 50 cards mature Mon Nov 9 — first mass settlement 16:15 Mon (prices land Mon evening under the provider's one-day PIT lag); Batch B 5-session 100 mature Tue Nov 10. Next new batch locks Mon Nov 9 evening against the Mon bar. |
| Research deliverable | Deep scan of how quant platforms make money vs our gaps: four URL-cited note files in `research_notes/How quant algos make money/` + synthesis report `reports/How quant algos make money.md`. Headline: the gate's HALT is correct — the test hasn't been taken yet (2 settled outcomes); the structural risks are edge size (~0.2% realistic) vs the 0.4% delivery hurdle and infrastructure-gated profit mechanics; the controllable leak is machine availability. |
| Operator reminder | Keep the PC awake Mon–Fri 16:00–21:30 IST while the box sleeps on power settings; the restart-on-failure hardening offer for the four scheduled tasks stands unexecuted. |
