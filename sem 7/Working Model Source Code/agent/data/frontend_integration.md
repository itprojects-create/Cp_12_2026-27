# Frontend Integration — agent-service v1

The frontend is a **separate consumer**. It talks only to `/api/v1` (REST) + the two
WebSockets below — never the DB, LLM gateway, or broker. Contract is frozen and
generated: `contract/openapi.json`, `contract/schemas.json`, `frontend-client/client.ts`.

## Base URL & CORS
- Dev: `FRONTEND_ORIGINS` (comma-separated) in `.env`; any `localhost` port is also
  allowed by regex, so Vite/Next dev servers work out of the box.
- Prod: set `FRONTEND_ORIGINS=https://your-app.example`.
- Credentials are allowed; send `Content-Type: application/json`.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/sessions` | Start an analysis session → `SessionStatus{id,status}` |
| GET | `/api/v1/sessions/{sid}` | Poll status; `decision` = `FinalDecision` when `done` |
| GET | `/api/v1/theses/{instrument}` | Thesis version history |
| GET | `/api/v1/theses/{instrument}/diff/{v1}/{v2}` | Two thesis versions + status change |
| GET | `/api/v1/health` | Liveness + configured models |
| GET | `/api/v1/arena` | Live population, seed bank, IR-weighted allocation |
| POST | `/api/v1/arena/founders` | Idempotent: birth the 8 preregistered founders |
| GET | `/api/v1/arena/events?since={seq}` | Transition log (replay by `seq`) |
| GET | `/api/v1/killswitch` | Kill-switch state |
| POST | `/api/v1/killswitch` | `{engage: bool, reason?: string}` — halt/release |
| GET | `/api/v1/audit/export?limit=N` | 5-yr audit bundle (sessions, theses, evo ledger, usage) |
| WS | `/api/v1/sessions/{sid}/events` | Typed stage frames; terminal `done`/`failed` last |
| WS | `/api/v1/arena/events` | Typed birth/death/status/resurrection frames |

## Typed client (no npm needed)
`frontend-client/client.ts` is generated from the contract:
```ts
const api = new AgenticOSClient(API_BASE);
await api.bootstrapFounders();
const state = await api.getArena();
api.subscribeArenaEvents((e) => render(e));            // births/deaths
const s = await api.createSession({ instrument: "RELIANCE.NS", as_of, interval: "1d" });
api.subscribeSessionEvents(s.id, render, done);
await api.setKillSwitch(true, "incident");
```
Regenerate after any backend schema change: `python scripts/export_contract.py && python scripts/gen_ts_client.py`
(the `tests/test_contract_snapshot.py` guard fails on unregen'd drift).

## Page suggestions
- **Live arena**: population table (`living`) + allocation weights + seed-bank tombstones;
  feed `subscribeArenaEvents` into a transition ticker.
- **Session view**: `subscribeSessionEvents` stage timeline → final `FinalDecision` card,
  with thesis diff via `/theses/{instrument}/diff`.
- **Ops bar**: kill-switch toggle + `/health` + `/audit/export` download.

## Notes / limits
- POST `/sessions` returns **503 while the kill switch is engaged**.
- WS streams are typed frames, never raw tokens; the arena socket is read-only.
- `/api/v1/eval/run` is still a stub (`not_implemented`).
