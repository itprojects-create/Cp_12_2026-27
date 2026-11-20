# Quant Plus V3.1 — Forecast worker readiness & operations runbook

**Date:** 2026-11-12 · **Scope:** W0.5 deliverable — how the scheduled forecast worker actually behaves today, what is verified, what is NOT verified, and the exact steps to make it durable.

---

## 1. Current readiness verdict

| Aspect | State | Evidence |
|---|---|---|
| Job registration (4 jobs, IST) | **VERIFIED** | QPForecastSettle 16:15, QPForecastDaily 16:30, QPForecastTournament 17:30, QPForecastCatchup 21:00 — weekdays; `D:\QP\agent-service\scripts\register-forecast-jobs.ps1` |
| Worker code path | **VERIFIED** | Runtime venv `D:\Quant-Plus\.local-data\backend-runtime\Scripts\python.exe`, cwd `D:\QP\agent-service`, module `quantplus_intelligence.forecast.jobs`; W0 changes synced into `D:\QP\agent-service\quantplus_intelligence\` |
| Heartbeat / missed-session detection | **SHIPPED, TESTED (offline)** | `forecast/heartbeat.py`; 9 tests in `backend-extension/tests/test_worker_reliability.py`; live `status` run produced `reports/alpha_v3_1/worker_heartbeat_status.json` |
| External alert route | **NOT_CONFIGURED** | `QP_ALERT_WEBHOOK_URL` is unset → status honestly reports `NOT_CONFIGURED`; no alarm delivery is possible yet (§3) |
| Uptime | **CONDITIONAL** | Task Scheduler actions use `InteractiveToken` + `StartWhenAvailable`/`WakeToRun` on a Windows 11 laptop. Jobs stop on sleep/logoff/power-off. **This is NOT an always-on worker and must not be reported as 24/7.** |
| Catchup correctness | **VERIFIED (idempotent, no backfill)** | Missed market sessions are *detected and alarmed*, never repaired by retro-forecasting. Catchup replays only what receipts say was missed, exactly-once. |

**Overall:** operational for as long as the laptop is awake and logged in. Every hard reliability gap (heartbeat coverage, missed-session alarm, idempotent catchup, honest CONDITIONAL labelling) is closed in code except the two operator actions in §3.

---

## 2. Daily operating procedure (normal day)

1. **16:15 IST** — `settle`: settles all cards whose `matures_on` session completed and have eligible prices. Exactly-once via the ledger's settle guard. Heartbeat `OK` appended to `data\forecast_reports\worker_heartbeat.jsonl`.
2. **16:30 IST** — `daily`: captures the new day's forecast batch (post-close).
3. **17:30 IST** — `tournament`: research tournament step (unchanged V2 behaviour).
4. **21:00 IST** — `catchup`: repairs any missed run **that has a job receipt**; no retro-forecast backfill of a session that simply never produced one.

**Morning check (one command):**

```
D:\Quant-Plus\.local-data\backend-runtime\Scripts\python.exe -B -m quantplus_intelligence.forecast.jobs status
```

Run from `D:\QP\agent-service`. Exit 0 + `overall: OK` is healthy. Meaningful states:

- `OK` per job — heartbeat recorded for the verified NSE session.
- `MISSED_SESSION` — a completed trading session has no heartbeat for a due job: investigate logs, run `catchup`.
- `UNMONITORED` — session predates heartbeat monitoring start (no coverage exists; **the status must never fabricate an alarm for pre-heartbeat history**). Verify manually via `schedule_daily.log` or run `catchup` if the day must not be lost.
- `NOT_DUE_YET` — job not yet due today (normal before its IST time).
- `NOT_CONFIGURED` — alert webhook unset (§3).

---

## 3. Operator actions required to reach full readiness (not code work)

### 3.1 Configure the alert route (5 minutes)

The worker can now raise named alerts (`MISSED_SESSION`, settlement faults, worker faults) but the destination is unset. To configure, set the environment variable for the account that runs the scheduled tasks — do **not** hardcode it in code, scripts, logs or git:

```
QP_ALERT_WEBHOOK_URL = <private webhook URL, set via System Environment Variables or the task's own environment>
```

Any HTTPS endpoint that accepts a JSON POST (e.g. a private Slack/Discord/NTFY-style hook) works. Until it is set, `worker_heartbeat_status.json` reports `alert_route: NOT_CONFIGURED` — that is the honest label, not an error.

### 3.2 Uptime decision (choose one)

| Option | Uptime class | Cost/effort | Notes |
|---|---|---|---|
| **A. Keep Windows laptop** | `CONDITIONAL` (current) | none | Sleep/logoff/power = missed sessions. Acceptable only while gaps are acceptable and alerts (3.1) are configured so misses are *seen*. Disable "sleep on battery/plugged-in" during market hours + auto-logon as mitigations. |
| **B. Always-on Windows PC / mini PC at home** | `SUBSTANTIAL` | hardware + config | Same scripts, same Task Scheduler; power settings hardened. Closest to current ops. |
| **C. Managed VM / cloud worker (recommended end-state)** | `ALWAYS_ON` (audit-eligible) | ₹/month | Run the same `quantplus_intelligence` package under a service manager (systemd/NSSM) on a small VM in IST timezone; secrets only in server env; NSE/FYERS data budgets stay on the server. Task Scheduler remains a verified fallback. |

Uptime is labelled from what is *actually running*, never from what is configured. No option converts to "always-on" on a sleeping laptop.

---

## 4. Verified failure modes and their handling

| Failure mode | Handling (verified in W0) |
|---|---|
| Machine asleep at 16:15/16:30 | Job misses the window; next `catchup` (21:00, or next boot + StartWhenAvailable) replays **settle** for due cards with prices. A missed *daily capture* is **not** recreated — no retro-forecast backfill, ever. |
| Interrupted run (partial batch) | Ledger exactly-once guard + job receipts: rerun settles/records only the remainder. Proven on Oct 30 cohort (23/23 settled after interrupted Nov 11 run completed). |
| Duplicate scheduled-task firing | Receipt-keyed idempotency; second run is a no-op (tested). |
| Calendar confusion (holidays, Muhurat special session) | `exchange_calendar.py` + verified `nse_calendar.json` (Nov 10 2026 Diwali holiday excluded; Nov 8 Muhurat special session excluded from normal horizons). |
| FYERS quota exhaustion / Yahoo missing rows | Settle leaves cards `MATURE_WAITING_FOR_PRICE` instead of inventing a price; never settles without real eligible prices. |
| Clock/timezone | All job times IST; ledger UTC stored/IST semantics fixed in code; heartbeat validates against the *verified* session date. |
| Secrets | None in code/logs/git; webhook URL env-only; no broker endpoints touched anywhere. |

---

## 5. What changed in W0 (additive only)

- **New file** `backend-extension/quantplus_intelligence/forecast/heartbeat.py`: append-only heartbeat JSONL, per-job `OK/MISSED/NOT_DUE_YET` for the verified session, `MISSED_SESSION` vs `UNMONITORED` distinction (pre-heartbeat history never fabricates alarms), `QP_ALERT_WEBHOOK_URL` alert route reporting `NOT_CONFIGURED` rather than assuming delivery.
- **Additive edits** to `forecast/jobs.py`: daily/settle/paper/catchup record heartbeats; new `status` verb. `bridge.py`/`shadow.py` edits are the W0.4 label fix (separate).
- **Tests:** 9 new tests in `backend-extension/tests/test_worker_reliability.py` (hermetic, tmp paths, no network).
- **Rollback:** delete `heartbeat.py`, revert the additive `jobs.py` edits, delete the two new test files. No data migration; ledger untouched.
- **Synced** to `D:\QP\agent-service\quantplus_intelligence\` so the registered scheduler runs the same code.

---

## 6. Acceptance against W0.5 criteria

| Criterion | Status | Evidence |
|---|---|---|
| Missed-market-session detection | **PASS** | `heartbeat.py` + tests; live `status` output shows UNMONITORED/NOT_DUE_YET semantics |
| Idempotent catchup without retro-forecast backfill | **PASS** | existing receipt-guard verified on Oct 30 cohort; no backfill path exists |
| Heartbeat persistence | **PASS** | `data\forecast_reports\worker_heartbeat.jsonl` (append-only) |
| External alert interface | **PARTIAL** | route implemented; destination `NOT_CONFIGURED` — operator action §3.1 |
| Uptime honesty | **PASS (as labelled)** | `CONDITIONAL` label with exact deployment options §3.2 |
| Restart/duplicate job verification on isolated fixtures | **PASS** | `test_worker_reliability.py` (9 tests) |
