# Quant Plus — Working Model Source Code

Quant Plus is an NSE market research and paper trading application. This submission includes both source repositories required to run it locally.

- `web/`: React and TanStack Start frontend, server routes, paper trading engine, database migrations, intelligence extensions, tests and supporting research evidence.
- `agent/`: Python FastAPI backend, market data integration, research agents, reference data and tests.

The six semester documents are in the repository's `sem 6` and `sem 7` folders. A compressed [demonstration video](../Project%20Demonstration%20Video.mp4) is included directly in `sem 7` and downloads with a normal Git clone. The original recording is preserved locally.

## Requirements

Use Node.js 22.14 or newer, npm, Python 3.11, and Git. The Python dependency lock was validated on Windows with Python 3.11.9. Provider-backed features require your own provider credentials; no credentials, broker tokens, local account records, virtual environments, installed packages or build outputs are included.

## Local setup

Open PowerShell in this `Working Model Source Code` folder. Install the frontend:

```powershell
Set-Location web
npm ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
Set-Location ..
```

Install the backend:

```powershell
Set-Location agent
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Set-Location ..
```

Configure `agent/.env` and `web/.env.local`. Set `WEBSITE_API_KEY` in the backend and `AGENT_SERVICE_API_KEY` in the frontend to the same private value. Set the frontend `AGENT_SERVICE_URL=http://127.0.0.1:8000`. Configure server-side model provider keys for AI research and chat, and Fyers credentials for broker market data, using the supplied environment examples. Leave hosted account flags unset to use a fresh local paper book. Hosted authentication and persistence use InsForge and require separately configured credentials and schema; see `web/INSFORGE_MIGRATION.md` and `web/migrations/`.

Start the backend in one terminal:

```powershell
Set-Location agent
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```powershell
Set-Location web
npm run dev
```

Open the local URL printed by Vite. Provider-backed features need valid credentials and internet access. Complete the Fyers login when using broker quotes; the helper is `agent/scripts/connect_fyers.py`. Paper trading uses virtual funds.

On Windows, after setup, `web/start-all.cmd` can start both services. The submitted PowerShell launcher resolves the sibling `agent` directory and its `.venv` relative to the checkout. Older internal guides contain the developer's original absolute paths; use the commands above for this submission layout.

## Checks

From `web`, use `npm run typecheck`, `npm test`, and `npm run build`. For backend tests, set `QUANTPLUS_BACKEND_PYTHON` to the absolute path of `agent/.venv/Scripts/python.exe` and run `npm run test:backend`; the submitted test runner defaults to the sibling `agent` directory. Additional test commands are listed in `web/package.json`.

The submission preserves current on-disk source, including uncommitted development changes. Semester PDFs are byte-for-byte copies with descriptive filenames. Existing Git histories and the original Lovable repository connection are kept outside this submission. Deployment has not been performed.
