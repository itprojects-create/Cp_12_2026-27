# LIVE OPERATIONS REPORT — unattended forward-research operation (2026-10-10)

**Baseline:** 362/362. **Final:** 390/390 green (28 new, 0 regressions, 0 deletions).
Freeze: `LIVE_FORWARD_FREEZE_V1` (`data/strategy_freeze_20261010.json`, verified MATCH).
No strategy logic, gate, or threshold changed. No LLM capital authority reintroduced.

## A. Scheduler

Jobs (`scripts/run_job.py` + `scheduler.py` registry): intraday-events (30min),
post-close (19:00 IST), settlement (21:00), weekly-forward (Fri), daily-health,
daily-snapshot, backup, monthly-audit — cron + schtasks instructions included.
Market calendar gates every job (NORMAL/WEEKEND/HOLIDAY/SPECIAL_MUHURAT;
operator holiday file, never invented). Missed runs surface as EXPECTED RUN
MISSING via the ops log. No OS jobs installed by this phase (registry + CLIs
ready; installation is an operator step in the runbook).

## B. Live collection

`run_post_close.py` (ordered, per-step isolated, dry-run supported) +
settlement sweep + intraday job. First live record: none yet this phase (Saturday;
sources unscheduled) — rehearsal LIVE_SHADOW probe path proven. Statuses flow to
health + ops log; failures never abort sibling steps.

## C. Health/alerts

`quantplus_health.py`: per-dataset status incl. SUSPICIOUS_ZERO (zero-record success
on trading days). Alerts: INFO/WARNING/CRITICAL, console+file always, webhook/email
only when configured (PENDING note otherwise), dedup windows (4h/24h/once),
durable log + resolutions. Active alerts today: 0.

## D. Backup

`backup_evidence.py`: raw + DBs (sqlite backup API) + snapshots + forward artifacts +
manifests, hashed manifest; `restore-rehearsal` into temp with hash + integrity +
snapshot checks — **rehearsed 2026-10-10: ok, 0 failures**. data/backups/ gitignored
(operational, not claim evidence).

## E. PIT correctness reissue (CORRECTNESS_REISSUE, not a new strategy)

Frozen v4 + frozen veto/costs/cadence; only static→per-rebalance-PIT changed
(non-strict, disclosed); new files (`*-PIT_*`), canonicals preserved; --pit refuses
without --out-tag.

| Book | Static (original, preserved) | PIT reissue (canonical now) | Δ |
|---|---|---|---|
| ₹10L narrow | ₹13,59,181 +35.9% / 5.6% / DD12.27% | ₹13,09,957 +31.0% / 4.91% / DD12.59% | −4.9pp |
| ₹10L broad | ₹25,99,423 +159.9% / 18.5% / DD10.8% | ₹21,41,239 +114.1% / 14.47% / DD17.87% | −45.8pp, DD+7pp |
| ₹50L narrow | ₹68,19,573 +36.39% / 5.66% / DD12.44% | ₹66,11,706 +32.23% / 5.08% / DD12.72% | −4.2pp |
| ₹50L broad | ₹1,33,49,766 +167.0% / 19.04% / DD10.89% | ₹1,07,40,759 +114.8% / 14.53% / DD18.04% | −52.2pp, DD+7pp |

All 4: 284 rebalances, 0 UNKNOWN-freezes, all PARTIAL (disclosed). Deterioration
accepted without retuning. REPORT language: ORIGINAL REPORTED RESULT (static files,
preserved) vs PIT-CORRECTED REISSUE (`*-PIT` files) vs CURRENT CANONICAL (PIT reissue).

## F. Corporate-action coverage

`audit_corporate_actions.py`: production store 0 records (honest — coverage of
fixtures proven in-test only). Verification levels defined VERIFIED (action +
disclosure + knowability) / PARTIAL / UNKNOWN; by-type/year/universe breakdowns
ready; UNKNOWNs never auto-filled.

## G. Membership quality

`audit_pit_membership_sources.py`: 4066 strict / 6525 non-strict intervals,
strict avg 17.1/50 (ratio 0.342 — degeneracy confirmed, not masked), non-strict
50.0, 4 cross-source ambiguities (PARTIAL-forcing), classes separated
(subscription: none, import path ready). Gaps: no per-row announcement ts
(effective_from proxy), no subscription feed.

## H. Forward operations

Clock week 1 judged (infancy), week-2+ pending Monday settlements. Forward records
(UNSETTLED-first) + maturity-gated exactly-once settlement live; agents see only
matured rows. Event counts queryable (§52 shape, all zeros today). Champion
F1-v4-as-shipped unchanged; arena refuses backtest-flagged judgments (tested).
v6/v7 + devil bill marked ARCHIVAL_RESEARCH (`data/archival_research.json`), no tokens spent.

## I. Freeze

`strategy_freeze_20261010.json` (LIVE_FORWARD_FREEZE_V1, hash `0f44687e3abb17cf`,
verified MATCH). Effective-config hashing (function sources + every threshold/cap +
universe/costs/blackout/gates/benchmark — not git hash). `forward_week.py --freeze`
quarantines drifted runs as NO_JUDGMENT (tested). Forking mints new id/fingerprint/
forward-start, old history untouched. Change classification documented
(OPS_ONLY/DATA_CORRECTNESS/RESEARCH_INFRA vs STRATEGY/GATE_CHANGE).

## J. Tests

Baseline 362 → final **390 green** (28 new: 5 scheduling, 3 health, 2 backup, 1
paper-PIT, 2 source-audits, 3 rehearsal, 5 forward-evidence, 5 freeze, 2 ritual).
Full-suite validations: 362 baseline, 390 final. Zero deletions, zero
regressions. One hardening flake (prior phase) did not recur; SQLite race stays
fixed (concurrency stress green).

## K. Remaining weaknesses (explicit)

1. No OS-scheduled jobs installed yet (registry + CLIs ready; operator step).
2. No live records collected (Saturday + unscheduled feeds; health shows NOT_COLLECTED).
3. Strict PIT degeneracy stands (non-strict + disclosure working mode).
4. Corp-action production coverage is zero (collectors proven hermetic).
5. Meeting-date extraction still approximated; subscription membership absent.
6. Calibration n=0; event experiment INFANCY; champion forward evidence pending Monday.
7. v6/v7 partial forever (ARCHIVAL, no tokens). Devil bill queued the same way.

*(End of report. Prior sections (§§1–12) untouched; no performance claim added or
strengthened. Truth is the product.)*
