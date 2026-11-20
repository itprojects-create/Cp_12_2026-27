# NEXT-PHASE REPORT — PIT, events, evidence classes, DSR, calibration (2026-10-10)

**Scope:** P0–P7 after the research-OS migration (269 baseline → 300+ suite).
**No burned-window tuning occurred.** Thresholds predeclared; correctness reruns
reported as-is, including deteriorations.

## A. PIT membership

* Implementation: `app/data/pit_membership.py` — interval model
  (`MembershipInterval`), `membership_at(universe, ts)` snapshot contract
  (members/hash/version/coverage/missing/pit_status/strict), hard PIT rule
  (`effective_from <= ts`, announcement-bound when known), UNKNOWN→freeze.
* Source: vendored `nse_index_membership_history.csv` (6525 rows, never edited),
  Nifty 50→`217`, Nifty 500→`221`. Strict sources = press_release/merger/amendment.
* Known gaps (disclosed, not fixed by retuning): strict mode degenerate (15–20/50 —
  the Amendment-1 finding, still true); cross-source re-inclusion overlaps counted as
  ambiguity forcing PARTIAL (e.g. GSPL); no per-row announcement timestamps, so
  `effective_from` is the knowability proxy (PARTIAL-grade limitation).
* Integration: `run_core_v4` + `replay_ledger` accept `dates/membership_fn` (default-off,
  legacy byte-identical — proven by test). Ineligible names exit via target 0 under
  normal turnover gates; UNKNOWN freezes the rebalance.
* Audit: `scripts/audit_pit_membership.py` — 300 weekly rebalances 2021–2026, **0
  violations, 0 unknowns** (two-reader cross-check vs legacy `members_at`).
* Correctness rerun (§9, live 36-name/1420-bar panel, thresholds untouched):
  **static CAGR 6.52% → PIT 5.95% (−0.57pp bias removed)**, MaxDD 18.4→18.86%,
  cost 0.0423→0.0429, 284 rebalances, 0 frozen. Deterioration preserved as measured.

## B. Announcement ingestion

* Sources: local JSONL feeds (`scripts/ingest_announcements.py --feed`) + best-effort
  NSE fetch (`--live`, any failure → []). No live feed scheduled yet — store is
  honestly empty (audit: 0 rows, 0 mismatches).
* Raw records (§11 all fields), deterministic `EV-{ex}-{hash12}` ids, append-only
  (no update/delete primitives — tested), same-payload idempotent with duplicate
  links, amendments preserved + linked (not discarded), near-dup detection,
  §17 batch manifests, §18 explicit failure log (4 failure kinds).
* Normalization: `NORM_V1` (NFKC/HTML/whitespace/boilerplate canonicalization),
  raw_hash + normalized_hash per row, hash-stability tested.

## C. Extraction

* Taxonomy: `EVENT_TAXONOMY_V1` (21 categories), legacy mapped, version-gated.
* Schema: `Extraction` model carries event content ONLY — identity/timestamps ride
  the deterministic record (smuggling rejected at the gate, tested).
* Abstention: `triage()` — empty/short/ambiguous → ABSTAIN with reason, never forced.
* Versioning: append-only `event_classifications` (record, version); reclassification
  adds versions; experiments pin taxonomy+classifier versions.
* Accuracy limitation (stated, not certified): **ECONOMIC PIPELINE READY —
  CLASSIFICATION ACCURACY NOT YET CERTIFIED** (no labeled real dataset; keyword
  rules + synthetic fixtures only).

## D. Blackout engine

* Rules: `BlackoutRule` model + frozen `BLACKOUT_FAMILY_V1` (B0 control, B1 session,
  B2 +next, B3 two-session), artifact `data/blackout_family_v1.json` byte-matched
  to code (test fails on drift). Session-granularity date windows.
* Capital boundary (§§71–72, tested): entries/increases may block; decreases and
  full exits NEVER blocked; nothing held → 0 (never creates); B0 never fires.
* DSL bridge: rules compile to EVENT_BLACKOUT ops; B0 = empty program.

## E. Evidence classes

* `ALPHA / RISK_CONTROL / EXECUTION / UNIVERSE / DATA_QUALITY` on every hypothesis
  (default ALPHA, backward compatible). Dispatch: ALPHA→frozen GATESET_V1
  (unweakened); RISK→`RISK_GATESET_V1` (tail improvement ≥10bps/day, no catastrophic
  increase, opportunity drag ≤2pp, cost ≤50bps, 30/10/20 minimums); EXECUTION→cost/
  turnover improvement without >50bps degradation; UNIVERSE/DATA_QUALITY→coverage/
  correctness gates (CAGR-neutral by design).
* Verdicts: ALPHA_PASS/RISK_PASS/EXECUTION_PASS/QUALITY_PASS/NO_ECONOMIC_VALUE/
  INSUFFICIENT_DATA/FORWARD_PENDING/KILLED. Proven: risk control with lower CAGR
  passes on tail wins; risk-only economics cannot pass the alpha gate.

## F. Forward experiment

* Manifest `data/event_blackout_v1_manifest.json` frozen 2026-10-10T16:07:30Z —
  RISK_CONTROL, B0–B3, minimums 30/10/20, RISK_GATESET_V1, membership source hash,
  taxonomy/classifier/ingestor versions. No outcomes inspected before freezing
  (run came 4s later).
* Harness `scripts/run_event_blackout_forward.py`: control vs B-arms on identical
  panel/caps/costs, per-bar PIT eligibility, §42 event rows (factual observables,
  joint portfolio-effect disclosure), §43 risk, §44 opportunity (no invented
  notionals), §45 components-only utility. Memory row EXP-00001 (EXPERIMENTING).
* Current state: **EVENT_FORWARD_INFANCY** — 0 announcements, 0 forward bars.
  Report `data/event_blackout_report_20261010.json` (§96, failure-first).
* No verdict forced; no early promotion possible (gate enforces minimums).

## G. Broad DSR

* Ledger `app/eval/trials.py` (DSR_REGISTRY_V1): append-only (no update/delete
  primitives — tested), idempotent registration, seeded history (12 return + 6
  research = 18; never undercounted).
* Recompute `scripts/recompute_broad_dsr.py` (live 391-name/1420-bar panel, zero
  LLM tokens): observed Sharpe **1.526** (vs 1.509 stored — data-vintage drift,
  disclosed), skew −1.19, kurt 12.14, null bar 0.67 over 13 trials → **DSR 1.0**.
* §55 verdict `data/broad_dsr_20261010.json`: historical + PIT-corrected (existing
  artifacts, as-is) + DSR + concentration (audit: FACT dependence) + beta (prior
  artifacts) + forward INFANCY — separate labels, never collapsed.

## H. Research calibration

* Plumbing: priors locked at proposal time (first-write-wins, no hindsight edits),
  outcomes settled at maturity, Brier + 5-bin reliability + over/underconfidence
  per stage, per-role value metrics, fair-comparison frames.
* Sample: **n=0 → INSUFFICIENT_CALIBRATION_SAMPLE** (CLI verified). Isolation tested:
  no capital-path module imports calibration or reads prior fields; priors absent
  from `FinalDecision` schema.

## I. Tests

* Baseline 269/269 (recorded pre-phase). New: 12 PIT + 7 event-store + 6 blackout (+6
  announcements earlier) + 8 event-blackout + 4 evidence-gates + 3 trial-ledger + 5
  calibration + 6 P7-integration = **51 new, 320 total, 320 green, 0 regressions.**
* No test deleted to force green. Three pre-existing behaviors corrected with
  replacement tests and documented reasons: (1) real-file cross-source overlaps are
  ambiguity-not-error; (2) zero-width datetime windows → session-date windows;
  (3) catastrophic-loss comparison sign in negative space.
* Known intermittent (pre-existing, NOT from this phase):
  `tests/test_hardening.py::test_cost_cap_breach_aborts_gracefully` fails rarely
  with `sqlite3.OperationalError` variants ("not an error" / "no more rows
  available") at `graph.py:_save_ckpt` commit, only in some multi-file orderings;
  passes alone and in full sequential/default runs (320/320 × 2 post-freeze).
  Triage per §80 — old assumption: the single shared `sqlite_conn()` (lru_cache)
  tolerates the 5-analyst ThreadPoolExecutor commit race always; observed: rare
  order/timing-dependent commit failure; none of the frame's modules
  (graph/gateway/technical/db) were touched by this phase; stable session code
  deliberately left unrewritten (fix risk > flake cost). Re-run clears it.
* Fixed during run, all admitted in-test: 2 fixture bugs (title-varying fp,
  30-cap day count), 2 rounding artifacts, 1 store-body deletion (repaired +
  re-verified), 1 wrong profit expectation (veto forfeits upside — mechanism, kept).

## J. Remaining weaknesses (explicit)

1. Strict-mode PIT degeneracy (15–20/50) — non-strict + disclosure remains the working mode.
2. No live announcement feed scheduled — event sample is zero; experiment cannot mature.
3. Meeting-date extraction unbuilt — effective≈publication approximation stands.
4. v6/v7 direction reads partial; Devil-off full bill still queued (ARCHIVAL_RESEARCH).
5. Calibration/agents value metrics await forward outcomes (n=0).
6. Per-rebalance time-varying membership is DONE in core/ledger but the canonical
   paper artifacts still use static universes (re-issue on next paper run).
7. Corporate-action PIT is schema + UNKNOWN-marking only (no verified history).
8. `Experimental` overlay path exists (tagged, default OFF, ablation verdict OFF).

*(End of report. Pre-migration findings unchanged in REPORT.md §§1–9; migration in
§10; this phase appends §11. Nothing rewritten, no claim strengthened.)*
