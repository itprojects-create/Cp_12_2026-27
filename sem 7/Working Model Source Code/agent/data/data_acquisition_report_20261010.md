# DATA ACQUISITION REPORT — official-data layer (2026-10-10)

**Baseline:** 320/320 green (recorded, not taken on trust). **Final:** 362/362 green.
**New tests:** 42 (9 framework, 6 announcements, 3 actions, 4 market, 4 institutional, 3 derivatives, 4 filings, 3 membership/import, 5 ops, 1 concurrency).
**Zero regressions, zero deletions.** No strategy logic or frozen threshold touched.
No CAPTCHA/auth/paywall bypass, no stealth scraping, no arbitrary-URL fetching anywhere.

## A. Sources implemented

| Dataset | Official source | Collector | Status | Coverage |
|---|---|---|---|---|
| NSE announcements | NSE corporate-announcements API | `nse/announcements.py` | IMPLEMENTED (live untested — NSE gating likely) | fixtures green; prod feed pending schedule |
| BSE announcements | BSE AnnGetData API | `bse/announcements.py` | IMPLEMENTED + ISIN cross-links | same as above |
| NSE/BSE corp actions | corporate-actions APIs | `nse|bse/corporate_actions.py` + `actions_store.py` | IMPLEMENTED | fixtures green; filing linkage + PIT confidence working |
| Equity EOD + delivery | NSE bhavcopy archives | `nse/equity.py` | IMPLEMENTED | layout-drift guard; adjusted prices UNAVAILABLE-marked |
| Indices/VIX/TRI | ind_close_all archives | `nse/indices.py` | IMPLEMENTED | TRI provenance per row |
| Bulk/block | NSE deal archives | `nse/deals.py` | IMPLEMENTED | verbatim clients, no inference labels |
| FII/DII provisional | fiidiiTradeReco API | `nse/institutional.py` | IMPLEMENTED | PROVISIONAL only, always |
| CDSL FPI final | manual import (primary) | `cdsl/fpi.py` | PARTIAL (auto-fetch refused by design) | cross-validation MATCH/MINOR/CONFLICT |
| F&O bhavcopy | fo bhav archives | `nse/fno.py` | IMPLEMENTED | exact source field names kept |
| Participant OI / volume | participant archives | `nse/fno.py` | IMPLEMENTED (separate tables) | never merged |
| FII derivatives stats | fii_stats archives | URL builder + schema validation | IMPLEMENTED_BUT_EMPTY (xls parse on demand) | — |
| PCR variants | derived, contract-level | `features_pcr.py` (PCR_DEFS_V1) | IMPLEMENTED | never scraped |
| Financial/shareholding XBRL | manual import (primary) | `nse/filings.py` + `xbrl.py` + `filings.py` | PARTIAL (session-gated auto) | revision PIT proven on fixtures |
| Membership history | vendored CSV (existing) | P0 layer + `membership_recon.py` | IMPLEMENTED | + recon PARTIAL source + manual importer |
| Attachments | NSE/BSE hosts only | `attachments.py` | IMPLEMENTED | allowlist-enforced, hashed, no OCR |

Shared framework (`app/data_acquisition/`): base contract + FetchStatus (10 states),
bounded HTTP (timeouts/retries/Retry-After/backoff/pacing/ETag), raw-first atomic
store with sidecars, content addressing, manifests, quality reports, scheduler
registry + cron/Task-Scheduler instructions, error log, health, checkpoints, ledger
(LIVE/BACKFILL/MANUAL_IMPORT + first-seen, never backdated).

## B. Historical backfill

Engine `scripts/backfill_data.py`: day/week/month chunking, checkpoint resume,
idempotent re-runs, stops (not hammers) on blocked sources. No bulk backfill
executed this phase (sources unscheduled; framework + resume proven in-test).

## C. Announcement pipeline

NSE per-symbol + BSE per-scrip collectors → raw artifacts → immutable event store
(dedup/amendment links) → triage → rule classification → versioned append-only
classifications → forward store. Attachments allowlisted + hashed. Cross-exchange
links on ISIN+date only (ambiguous never force-linked). **Forward-eligible events: 0**
(experiment stays INFANCY — correct, §79).

## D. Market data

OHLCV (present-only fields) + delivery qty/pct, §87 validation flags (never repaired),
adjusted prices explicitly UNAVAILABLE, indices with TRI provenance, month-partitioned
parquet upserts. yfinance provider retained as research-grade fallback (labeled vendor).

## E. Institutional and derivatives

Bulk/block verbatim, FII/DII PROVISIONAL vs CDSL FINAL kept separate with graded
comparison, F&O contracts with OI>=0 flags, participant OI/volume in separate tables,
PCR computed from contracts (3 versioned variants, zero denominators → None).

## F. Fundamentals

XBRL parser decoupled from ingestion (version-aware, unknown tags ignored, drift-safe);
filings carry broadcast-based availability (period-end never gates — leakage-tested);
revisions append (pre-revision as_of sees v1 — tested); shareholding same machinery;
sanity checks detect-only (figures never altered).

## G. Index membership

Prior P0 layer operational (300 weekly audits, 0 violations). This phase: source
classes carried end-to-end (subscription vs reconstruction never equivalent),
press-release recon table with leakage-shape rejection, manual subscription importer
(hashes + validates + registers provenance). Verdict: **PARTIAL — verified
subscription feed still required** for full confidence.

## H. Corporate actions

§19 normalized store (idempotent), filing linkage with kind-consistency grading
(VERIFIED/PARTIAL/UNKNOWN), PIT visibility by knowability (not ex-date),
factor-bearing VERIFIED rows sync to the researched PIT table (others reported
skipped, never coerced).

## I. Data quality

Per-collector quality reports (§45 fields), §87 row flags, staleness evaluation in
`data_health.py` (today: all NOT_COLLECTED — shown, not faked), disagreements graded
MATCH/MINOR_DIFFERENCE/CONFLICT and stored unresolved, schema fingerprints per layout
with drift → SOURCE_SCHEMA_CHANGED (raw preserved).

## J. Operations

`update_market_data.py` (post-close + --settlement sequences, per-dataset isolation),
`backfill_data.py` (resume), `data_health.py` (table + infra economics),
`freeze_data_snapshot.py` (SNAP-20261010 frozen: 11 datasets, 0 artifacts),
`scheduler.py` (4 windows, cron + schtasks instructions), `import_dataset.py`
(manual path), `ingest_announcements.py`, `audit_event_store.py` (0 rows, 0 mismatches).
SQLite race (§64): reproduced (7 errors, production strings) → thread-local + WAL +
busy-timeout → stress 3×200 ops clean; hardening tests green.

## K. Tests

Baseline 320 → final **362 green** (42 new across 10 files; concurrency 1, ops 5,
announcements 6, actions 3, market 4, institutional 4, derivatives 3, filings 4,
membership 3, framework 9 — plus fixes). No deletions. Full-suite validations: 320
baseline, 362 final (incl. one contract regen for new audit endpoints). One
intermittent pre-existing hardening flake documented previously did not recur in
final runs (SQLite race now hardened with a reproducing stress test).

## L. Remaining blockers (explicit)

1. No live collection scheduled yet — all feeds NOT_COLLECTED in production (collectors
   proven hermetic; first scheduled runs will populate health).
2. NSE archive/API gating (401/cookies) probable on first live runs — handled as
   SOURCE_BLOCKED with manual-import fallback, not worked around.
3. CDSL finals + XBRL filings depend on manual imports (by design).
4. FII-derivatives-stats XLS parsing on demand (fixture is CSV-shaped).
5. Membership subscription feed still required for VERIFIED grade.
6. Meeting-date extraction (classifier v2) still approximated by publication_ts.
7. v6/v7 direction reads + Devil-off bill unchanged (out of scope, ARCHIVAL).

*(End of report. Strategy-performance claims: none added, none strengthened.)*
