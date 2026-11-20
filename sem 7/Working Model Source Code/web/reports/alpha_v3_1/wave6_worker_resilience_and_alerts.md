# W6 worker resilience, alerts and runbook

**Hosting:** `WORKER_NOT_DURABLE` · **Webhook:** `WEBHOOK_NOT_CONFIGURED` · **Delivered alerts:** 0.

The server-owned worker contract is calendar-aware in IST, leased, idempotent and receipt-backed.
Offline tests cover duplicate triggers, restart/replay, stale/closed/holiday sessions, missed-run
catch-up without retroactive quotes, clock rollback, provider failure, pause/resume and expired
heartbeat. Pausing blocks `signal_evaluation` but preserves execution monitoring for risk-reducing
exits, action checks, settlement, marks and alerts. Fixture receipts include successful and
`MISSED_CATCH_UP` cases; fixture alert delivery is not claimed.

Local health command (read-only):
`python scripts/wave6_worker_service.py --ledger <forward.jsonl> --health-once`.
The localhost `/health` wrapper is default-off and refuses service mode unless
`QUANTPLUS_W6_ENABLED=true`. For later operator-approved hosting, run the same container/service on
an always-on host with a persistent volume, restart policy, external watchdog, private env/secret
store, outbound allowlist, spend cap and rotated credentials. Do not count a sleeping Windows PC
as durable. No cloud resource or paid service was provisioned.

Fixture worker: 3 receipts; chain health
`True`. Real worker jobs remain unactivated because no
candidate/feed/hosting approval exists.
