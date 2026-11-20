# Prereg: PIT universe rebuild from membership history (bias killer)

**Written:** before any PIT-universe code or rerun. Deterministic, zero tokens.
**Source:** D:\Model\data\reference\nse_index_membership_history.csv (6,525 rows,
42 indices; Nifty 500 = index_id 221 with 1,123 spells from 2014-01-01; Nifty 50
= 217 with 83 spells). Vendored upstream file — NEVER edited in place; read
via configurable path (`PIT_MEMBERSHIP_PATH` env or Model default).
**License:** CC BY 4.0 data — attribution required. Every report using it must
carry: "Membership: Jha, A. (2026). NSE Historical Membership (Point-in-Time).
github.com/aditya-jha/nse-historical-membership. Derived from public NSE
Indices press releases and NSE circulars. CC BY 4.0."

## 1. Source-confidence rule (adapted with documented deviation)

Upstream provenance doc says filter `source IN ('circular','merger')`, but the
actual file's values are press_release/snapshot_floor/snapshot/merger/amendment
— no 'circular' rows exist. Press releases ARE the PR-backed evidence, so:
STRICT = {'press_release','merger','amendment'}; snapshot_floor/snapshot are
weak rows, included only in non-strict mode with disclosure. Deviation recorded
here, not hidden.

## 2. Step-1 scope: start-date membership (deliberate partial fix)

`members_at(index, start_date)` = symbols with valid_from <= start <=
(valid_to or open), strict sources, renames applied via nse_symbol_renames.json,
then + ".NS" (verbatim, matching nifty500.txt convention).
This removes FUTURE JOINERS (the dominant survivorship channel: stocks that
entered later and ran up) but keeps mid-window exits contributing full series
(their post-exit years still count). Residual bias disclosed, direction UP.

Full per-rebalance time-varying membership (= core-loop change = rule change)
is explicitly v5-future-work, not this step. Universe construction is INPUT
DATA, not selection logic — v4 rule file untouched.

## 2b. Amendment 1 (same day, pre-rerun): strict mode is degenerate

Strict filtering (press_release/merger/amendment only) yields 15/50 Nifty-50
names @2021-01-01 and 2/50 @2015-01-01 — the snapshot_floor rows ARE the roster
backbone, and excluding them replaces survivorship bias with a worse certain
error (70% of the index missing). For start-date membership, a snapshot_floor
spell covering the date is positive membership evidence. Decision: reruns use
strict=False with weak-row counts recorded in every artifact (50/50 and
502/513 names recovered, vs 15/2 under strict). Module default stays strict
(safe default for other uses); call sites pass strict=False explicitly.

## 3. Diagnostic rerun (bias measurement, NOT a new claim)

One rerun each: v4 narrow + broad on PIT-start universes over 2021-2026.
Purpose: the DELTA vs static-list results quantifies the survivorship effect
size in rupees. No PASS/FAIL shopping: whatever prints is recorded; the only
predeclared expectation is direction (numbers drop). Trial registry +2 with
`s survivorship-diagnostic` tag (excluded from future DSR headline math —
diagnostics are not configurations).

## Gate

Module + tests green (boundary inclusion, strict/non-strict, renames, future-
joiner exclusion, missing-file raise). Rerun outputs `*_pit.json` siblings;
frozen originals untouched. Attribution string present in every new artifact.
