# W5 living research journal, monitoring and alerts

**Evidence time:** 2026-11-14T09:05:10.030883+00:00 · **Maturity:** `ENGINEERING_CHECK_SYNTHETIC`

The W5 journal is independent of W2/W3/W4 and hash-chained at
`wave5_research_monitor_log.jsonl`. Chain status: **chain intact**;
6 immutable events; head `d1abaa95a561ce8ea87489846373bb9dabce0bf06859084b15caed7a25542bca`.

## Controlled conclusion change

1. Baseline event retained conclusion `RESEARCH_DIAGNOSTIC` at 09:11 UTC.
2. A different evidence hash at 09:12 UTC changed conclusion to `REJECTED`.
3. Exactly one `HIGH` alert was created with canonical ID
   `29c958f9f0548fb65bb479578f1b2d42fdff4d71ddd353257593e7892db03021` and first-seen event hash
   `394bac50c776672ce90c496768d907e4034dba762ce4991e9ef342f4d20bf6f0`.
4. Replaying the identical adverse check appended no check and no alert.
5. Delivery is `DRY_RUN_NOT_DELIVERED`; `QP_ALERT_WEBHOOK_URL` is not configured and no
   acknowledgement exists. No notification delivery is claimed.

This is an engineering demonstration, not a real strategy signal or market-performance alert.

## Registered periodic checks

- `CORPORATE_ACTION_COVERAGE` — verified actions for every eligible window
- `DATA_FEED_COVERAGE_FRESHNESS` — coverage and newest source timestamp
- `EVENT_CLASSIFIER_LABEL_STABILITY` — blind label/adjudication stability
- `EXCHANGE_CALENDAR_VALIDITY` — calendar verification and horizon
- `FEE_SCHEDULE_EXPIRY` — effective/expiry coverage for evaluation cutoff
- `FORWARD_SIGNAL_AVAILABILITY` — append-only forward signal existence
- `JEV_SERVING_MODEL_ALIAS_DRIFT` — requested alias versus returned model identity
- `MISSED_SCHEDULED_JOBS` — expected job receipts versus observed receipts
- `RISK_COST_SENSITIVITY` — eligible net result under stressed costs
- `W3_CANDIDATE_DIAGNOSTIC_DRIFT` — fixed-cutoff candidate diagnostic delta
- `WORKER_HEARTBEAT` — local worker heartbeat freshness and successful state

Financial drift and cost checks return `DATA_BLOCKED` while valid net returns are unavailable.
The scheduler supports only explicit dry-run/no-network mode in W5. The local worker predicate
checks a real supplied heartbeat timestamp/state against a fixed freshness bound. Windows Task
Scheduler remains conditional on machine uptime; durable hosting is an operator decision, not a
W5 deployment.

Acknowledgement and resolution are append-only event types; this demonstration deliberately
leaves the synthetic alert open/unacknowledged to avoid claiming operator action.
