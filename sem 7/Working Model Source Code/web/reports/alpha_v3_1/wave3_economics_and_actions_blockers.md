# Wave 3 — Economics and Corporate-Actions Blockers (remediation checklist)

Status: **DATA_BLOCKED / INCONCLUSIVE** for all real-history net economics.
This document is the dedicated remediation checklist required by the W3
handoff (§6). Engineering progressed without weakening any gate; no third-party
data was fetched, and no right was assumed.

## 1. Unverified corporate actions — exact scope

- **State:** no verified local source exists for historical splits, bonuses,
  dividends, consolidations or demergers (`adjustment_factor` returns
  `UNKNOWN` and abstains; no factor is ever imputed from price gaps).
- **Quantified contamination:** the W1 reproduction quantified **31
  contaminated name-month windows** (action-shaped raw-price discontinuities
  inside label windows). W3 carries the same discipline forward:
  - every W3 label whose `[entry, exit]` window contains a close/prev_close
    ratio outside **[0.65, 1.54]** is typed `DATA_BLOCKED_ACTION_WINDOW` and is
    **excluded from all cross-sectional statistics** (rank IC, Brier, MAE);
  - verified and unverified action windows are conservatively excluded
    alike; the W2 anchor showed the violation mechanism concretely (a MARUTI
    availability violation was caught and rejected by the leakage challenge).
- **Verified-source requirements for unblocking:**
  1. a dated, source-hashed corporate-actions dataset with
     security-identity mapping (ISIN preferred; symbol rename continuity),
  2. action kind, effective date AND ex-date per row,
  3. point-in-time availability timestamp for each action row (when it was
     knowable), so PIT gating can consume it,
  4. unit tests on deliberately discontinuous prices before the factor
     ledger is trusted (dividends and TRI handled consistently with the
     benchmark comparison — never pretend a raw-price index is TRI).

## 2. Fee schedule history

- Fee truth starts **2026-03-01** (`nse-cm-delivery-2026-03-01`, the tested
  W0 paper-book model). Every label window before that date carries
  `charges_status = SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE` and
  `net_absolute = None`. **NET_ABSOLUTE for the entire W3 train/validation
  span (2015-06-01 .. 2023-12-31) is DATA_BLOCKED** — it is never filled with
  0% or an estimate.
- **Remediation:** a historically dated fee schedule (brokerage slabs, STT,
  GST, exchange and SEBI fees, stamp duty, DP charges) with verified effective
  dates per component, source-hashed. Until then no cost sensitivity verdict
  can be anything but `INCONCLUSIVE` (typed as such in every W3 challenge
  report).

## 3. Benchmark basis mismatch

- Fills are on **raw unadjusted** bhavcopy prices; the official benchmark
  (`NIFTY50_TRI`) is dividend-inclusive total return. `v3_benchmark_relative`
  computed on this mixed basis is **NOT economically interpretable**, so W3
  types every label `DATA_BLOCKED_BASIS_MISMATCH` and discloses the raw
  diagnostic number separately (`benchmark_relative_raw`) with the caveat.
- **BENCHMARK_RELATIVE stays DATA_BLOCKED** until adjusted (verified-action)
  fills and a same-basis benchmark exist. The W3 comparison artifacts report
  gross ranking diagnostics only; no column upgrades a gross number to cash.

## 4. 2024 H1 missing span, membership and sector provenance

- **2024-01-01 → 2024-06-20 MISSING_SPAN:** no official bars; W3 windows never
  bridge the hole (lookback windows containing archive gaps abstain; label
  exits extend only with the labelled conservative flag). Unblocking
  requires a verified official-bar source for the span.
- **Membership spells:** weak (`snapshot_floor`) spells are backward-walk
  upper bounds; strict (press-release) coverage is thin pre-2018. W3 records
  `membership_strict` per label and discloses the strict/weak mix per fold.
  Every membership row carries the CC BY 4.0 attribution (Jha, A. 2026).
- **Sector map: UNAVAILABLE.** No source-verified, as-of historical sector
  classification exists, so **sector-relative features are never emitted**
  (documented blocker, not a zero). Remediation: a dated, source-verified
  sector/industry map with effective dates; only then can sector-relative
  features enter the preregistered vector (version bump required).
- **2026-09-18 → present:** vendor-only (`VENDOR_RECONSTRUCTION`), excluded
  by construction; and no data beyond that exists in the archive, hence
  `NEW_SEALED_HOLDOUT_UNAVAILABLE` (see `wave3_forward_protocol.md`).

## 5. Strictly clean development sub-window — deliberately NOT cherry-picked

A "clean" sub-window (no unverified action crossing any evaluated label) could
be constructed by *observing which windows are contaminated* and then
evaluating only the remainder. That selection is conditioned on the data being
avoided, so W3 does **not** carve one out for reporting. The honest
alternatives implemented instead:

1. per-label typed admissibility (block reasons disclosed per fold), and
2. walk-forward folds that keep every fold's *training* rows purged/embargoed
   regardless of contamination, with contamination disclosed per label.

Any future clean-window analysis must pre-register the window and the rule
*before* looking at label outcomes.

## 6. Data rights / licence constraints

- Bhavcopy/TRI: official NSE/NSE Indices records, personal-research use per
  `MANIFEST.md`; not for redistribution as a dataset.
- Membership/renames: CC BY 4.0, attribution carried on every row.
- No scraped data from paywalled or ToS-restricted sources; no unsanctioned
  third-party fetching happened in W3.

## 7. What unblocks Wave 4 (in priority order)

1. verified dated corporate-actions ledger (with PIT availability), enabling
   adjusted-price labels and same-basis benchmark-relative economics;
2. historically dated fee schedule(s) enabling net absolute economics over
   any train/validation window;
3. verified official bars for 2024 H1;
4. verified sector map for sector-relative features;
5. a genuinely fresh, sealed forward window (see forward protocol) — the
   revealed W2 holdout (2024-06-21 .. 2026-09-17) can never be reused.
