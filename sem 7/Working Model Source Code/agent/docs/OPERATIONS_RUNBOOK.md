# QUANTPLUS OPERATIONS RUNBOOK (mandatory, §69)

## Daily

* **Post-close** (`python scripts/run_job.py --job post-close` or `run_post_close.py`,
  19:00 IST weekdays): ordered EOD → indices → deals → flows → F&O → corp-actions →
  announcements → registry → snapshot. Check: artifact JSON statuses, snapshot file.
* **Settlement** (`--job settlement`, 21:00 IST): amendment sweep + filings check.
* **Health** (`python scripts/quantplus_health.py`, 21:30 IST): every dataset must be
  HEALTHY or explicitly NOT_COLLECTED/stale — never faked. Zero-record SUCCESS on a
  trading day is SUSPICIOUS_ZERO, investigate.
* **Snapshot** (`freeze_data_snapshot.py`, with post-close): validate before settlement use.

## Weekly

* **Forward ritual** (`forward_week.py`, Friday after close; full order via
  `weekly_ritual.py --day`): health → snapshots → settle → evidence → judge →
  calibration → memory → foundry-if-allowed → report (.json + .md) → freeze →
  backup. Verdicts: judged / NO_JUDGMENT (drift/missing data — quarantined, never forced).
* **Reconciliation** (`data_health.py` + `audit_event_store.py`, Sunday).
* **Backup**: daily incremental + Sunday full; restore rehearsal monthly at minimum.

## Monthly

* **Audit** (`monthly_audit.py`, 1st Sunday): coverage, PIT quality, corp-actions,
  latency, schema drift, failures, restore test, snapshot integrity, config drift,
  trial + cost ledgers. Operations-only recommendations — never parameter advice.

## Failure procedures

| Failure | Automatic | Operator inspects | MUST NOT |
|---|---|---|---|
| NSE announcement failure | retry→log→SOURCE_UNAVAILABLE alert | endpoint/cookies, schedule manual feed | bypass access controls |
| BSE failure | same as NSE | BSE API shape (schema drift?) | force-link without ISIN |
| Schema drift | raw preserved, SOURCE_SCHEMA_CHANGED | new columns vs mapping | map columns by position |
| Market data missing (trading day) | PARTIAL, checkpoint holds | source status, holiday file | invent prices |
| Corp-action conflict | both versions kept | disclosure linkage | overwrite provisional |
| Snapshot invalid | marked INVALID, unused for settlement | artifact hashes | settle against it |
| SQLite failure | busy-timeout + per-thread conns | disk space, WAL files | delete the DB |
| Backup failure | alert CRITICAL | dest disk, permissions | skip the next backup |
| PIT UNKNOWN | rebalance frozen (no changes) | membership source | liquidate on UNKNOWN |
| Config drift | NO_JUDGMENT quarantine | diff sections | judge under drift |

## NEVER manually invent data (§72)

Prohibited: filling missing prices, inventing timestamps, editing first-seen
values, modifying event outcomes, changing a manifest after freeze. Violations
invalidate forward evidence — fork a new experiment instead.

## Recovery

* Rerun idempotent collector (same args — hashes dedup).
* Resume failed backfill (`backfill_data.py` continues from checkpoint).
* Rebuild normalized data from raw (parquet upserts are idempotent).
* Restore database (sqlite backup file → verify `PRAGMA integrity_check`).
* Verify hashes (`audit_event_store.py`, snapshot validation).
* Resume weekly ritual (windows are numbered; missed weeks stay missing, never backfilled as judgments).

## Disaster recovery test

`backup_evidence.py restore-rehearsal --backup <dir>` into temp; verify snapshot
IDs, event store counts, registry rows, forward artifacts, research memory.
Performed 2026-10-10: ok, 0 failures.
