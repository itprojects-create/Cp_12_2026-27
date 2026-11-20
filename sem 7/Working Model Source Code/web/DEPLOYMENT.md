# Deploying Quant Plus on InsForge

## Current deployment choice (2026-11-21)

The user requires **zero recurring cost**. The active preparation is now one Oracle
Always Free ARM VM for both web and agent containers, with the existing InsForge
backend within its free quotas. See [the free deployment runbook](deploy/free-tier/README.md)
and `node scripts/prepare-free-deployment.mjs --domain <hostname>`.
Oracle signup is blocked: the user has no credit card and needs a no-card setup.
The replacement hosting route is pending; nothing has been published. Paid InsForge compute
commands below describe the earlier proposal and must not be run for this release.
The web Dockerfile now takes public `VITE_*` build arguments; all `.env*` files are
excluded from Docker build contexts. Runtime secrets remain server-only.

The older sections below are retained as historical preparation notes.

Status (2026-10-20): **prepared, not deployed.** The app runs locally in hosted
InsForge mode (InsForge sign-in and the hosted paper book). Nothing below has
been run against the cloud yet. Run it when you are ready to publish; the
commands create billable compute.

Update (2026-11-20), release preparation (Phase 1) done locally:

- Both images build (`docker build` in each repository) and run together:
  web container → agent container → market data verified end to end, the
  agent health check passes, and `.dockerignore` keeps `.env*`, `.local-data`
  and broker tokens out of both images.
- `npm run lint`, `npm run typecheck`, `npm test` (125 tests + script suites)
  and `npm run test:intelligence` (789 tests) pass.
- The agent service now holds **durable data** that compute without a disk
  would lose on restart (see "Persistent data" below). The recommended layout
  is therefore hybrid: web app on InsForge compute, agent service on a small
  Mumbai VM with a persistent disk.
- The secrets lists below now include the Experiential Labs and Inception
  model gateways.

## Persistent data (agent service)

| File (under `D:\QP\agent-service\data`)                   | Size (Nov 2026) | Loss on restart                                                 |
| --------------------------------------------------------- | --------------- | --------------------------------------------------------------- |
| `forecast_ledger.sqlite3` (`FORECAST_LEDGER_PATH`)        | ~3.5 MB         | **Unrecoverable**: hash-chained, forward-only forecast evidence |
| `news_archive.sqlite3` (`INTELLIGENCE_NEWS_ARCHIVE_PATH`) | ~135 MB         | News/sentiment history; cannot be re-fetched                    |
| `sentiment_history.sqlite3` (`INTELLIGENCE_HISTORY_PATH`) | small           | Sentiment time series                                           |
| `quantplus.db`                                            | ~16 MB          | Prediction/session cache (rebuildable)                          |
| `fyers_private/tokens.json`                               | tiny            | Fyers token; daily re-login anyway                              |

Copy these to the server's persistent disk while the local backend is stopped,
then confirm the forecast ledger chain verifies on the server. Back them up
nightly, off the server.

## Scheduled jobs

These four jobs run in Windows Task Scheduler on the development PC today:
`QPForecastDaily`, `QPForecastSettle`, `QPForecastTournament` and
`QPForecastCatchup` (see `scripts/register-forecast-jobs.ps1`). Recreate them as
cron jobs on the agent server at the same IST times, then **disable them on the
PC** so that two machines never write to the ledger.

## Architecture

| Service                                     | Source                               | Where            | Why                                                                                                                         |
| ------------------------------------------- | ------------------------------------ | ---------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Web app (SSR + paper worker)                | `D:\Quant-Plus` (`Dockerfile`)       | InsForge compute | The worker settles resting orders and protections with no browser open, so it must be a long-lived process, not serverless. |
| Agent service (market data, Fyers feed, AI) | `D:\QP\agent-service` (`Dockerfile`) | InsForge compute | Holds the Fyers WebSocket and research jobs in one process.                                                                 |
| Database, auth, paper book                  | InsForge project `Quant-Plus`        | Already live     | Owner-scoped RLS; the book commits through `paper_commit_book`.                                                             |

Region: use Fly's Mumbai region (`bom`) for both services to keep latency to
NSE and to each other low.

## Before you deploy

1. Docker images: `docker build .` in each repository should succeed. This was
   not verified in the preparation run (the Docker engine was not running).
2. Install `flyctl` (InsForge source-mode deploys use it for the remote build;
   no local Docker daemon is needed for the deploy itself).
3. Fyers: add the deployed web URL to the Fyers app's redirect URLs. Each
   container restart clears the Fyers token (compute has no persistent volume),
   so sign in to Fyers again after a restart.
4. Compute has no persistent disk. The hosted paper book is in InsForge Postgres
   and is unaffected; the agent service's SQLite research cache and the web
   app's last-known market cache rebuild after a restart.

## 1. Agent service

Create `D:\QP\agent-service\.env.production` (never commit it) with the backend
secrets from `.env`:

- Model gateways: `INCEPTION_API_KEY`, `INCEPTION_MODEL` (current provider),
  `EXPLABS_API_KEY`, `EXPLABS_BASE_URL`, `EXPLABS_MODEL`, `OPENROUTER_API_KEY`,
  `OPENROUTER_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`,
  `OPENROUTER_ANALYST_MODEL`, `OPENROUTER_DECIDER_MODEL`, `OPENROUTER_MAX_TOKENS`.
- Spend limits and policy: `SESSION_TOKEN_CAP`, `DAY_TOKEN_CAP`, `DAILY_REQUEST_CAP`,
  `DIRECTION_POLICY`, `ANALYST_MODEL`, `DECIDER_MODEL`.
- `WEBSITE_API_KEY` (shared with the web app's `AGENT_SERVICE_API_KEY`).
- `FYERS_CLIENT_ID`, `FYERS_SECRET_KEY`,
  `FYERS_REDIRECT_URI=https://<agent-domain>/api/v1/fyers/callback`.
- Data paths on the persistent disk: `FORECAST_LEDGER_PATH`,
  `INTELLIGENCE_NEWS_ARCHIVE_PATH`, `INTELLIGENCE_HISTORY_PATH`.
- `FRONTEND_ORIGINS=https://<web-app-domain>`.

Legacy `CODECRAFT_*`, `DAHL_API_KEY`, `DATABASE_URL` and `MONGO_URL` can stay
empty.

```powershell
cd D:\Quant-Plus
npx -y @insforge/cli compute deploy D:\QP\agent-service --name quantplus-agent `
  --port 8000 --memory 1024 --region bom --env-file D:\QP\agent-service\.env.production
```

Note the service URL it prints.

## 2. Web app

Public browser values are compiled into the build. Create
`D:\Quant-Plus\.env.production.local` containing **only** public values:

```dotenv
VITE_QUANT_PLUS_AUTH=insforge
VITE_INSFORGE_URL=https://htaen3qu.us-east.insforge.app
VITE_INSFORGE_ANON_KEY=<public anon key>
# optional analytics: npx -y @insforge/cli posthog setup
VITE_POSTHOG_KEY=<phc_ key>
```

Create a separate runtime secrets file, e.g. `D:\Quant-Plus\.local-data\web.production.env`
(inside the ignored folder), with server-only values:

```dotenv
QUANT_PLUS_BOOK_PROVIDER=insforge
INSFORGE_URL=https://htaen3qu.us-east.insforge.app
INSFORGE_API_KEY=<admin key — server only>
INSFORGE_ANON_KEY=<public anon key>
AGENT_SERVICE_URL=<agent service URL from step 1>
AGENT_SERVICE_API_KEY=<same as WEBSITE_API_KEY>
EXPLABS_API_KEY=<key>          # Quant AI chat provider since 2026-10-28
EXPLABS_BASE_URL=<url>
EXPLABS_CHAT_MODEL=<model>
OPENROUTER_API_KEY=<key>       # fallback
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_CHAT_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
```

```powershell
cd D:\Quant-Plus
npx -y @insforge/cli compute deploy . --name quantplus-web --port 3000 `
  --memory 1024 --region bom --env-file .local-data\web.production.env
```

Then in InsForge auth settings, add the web URL to the allowed redirect URLs
(`npx -y @insforge/cli config` — see the insforge-cli skill).

## 3. Verify

- `/` loads; `/app/dashboard` redirects to sign-in; sign in with the migration
  owner email and confirm cash ₹9,92,910.50 and 10 HDFCBANK.
- `/api/local` without a session returns 401.
- With Fyers signed in, a stock page shows "Live" and the index strip ticks.
- Run the worker check below.

## Still open before inviting other users

- **Worker-closed-browser check** (from `INSFORGE_MIGRATION.md`): with a
  throwaway account, place a resting LIMIT order during market hours, close
  every browser tab, and confirm the server fills it at the limit. Needs live
  Fyers quotes; not yet run.
- Custom domain: `npx -y @insforge/cli domains ...`.

## Rollback

- Web app: `npx -y @insforge/cli compute stop <service-id>`.
- Local hosted mode: remove `QUANT_PLUS_BOOK_PROVIDER` and `VITE_QUANT_PLUS_AUTH`
  from `.env.local` and restart. The local book is frozen at the 2026-10-20
  cutover state; any hosted trades after that would need reconciling first
  (`node scripts/compare-hosted-book.mjs` shows the difference).
