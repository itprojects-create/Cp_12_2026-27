# Wave 3 — Input Data and Split Audit

Scope: what W3 actually consumed, with hashes, date ranges, gaps, provenance
labels and the quarantine discipline. Written from the checked-out sources and
the W1 provenance artifacts (`pit_source_integrity.json`,
`historical_nse_data_coverage_and_rights.md`), not from assumptions.

## 1. Observed inputs (read-only; nothing fetched)

| Input | Path | SHA-256 (first 16) | Rows / size | Class |
|---|---|---|---|---|
| NSE EOD bhavcopy archive 2015–2026 | `D:\Model\NEW DATA\nse_eod_bhavcopy_2015_2026_full.csv.gz` | `4df01085a17f2bd2…` | 5,232,265 rows, archive built 2026-09-18 | OFFICIAL_EXCHANGE_RECORD |
| NSE index membership history | `D:\Model\data\reference\nse_index_membership_history.csv` | `75ebfac3b5d1fb22…` | 6,525 rows | PRESS_RELEASE_RECONSTRUCTION (CC BY 4.0, Jha 2026) |
| NIFTY50 TRI official series | ingested into warehouse `benchmark_bars` | `d92d1a97…` (per W1 integrity report) | — | OFFICIAL_EXCHANGE_RECORD |
| Derived warehouse | `backend-extension/data/research_v3/warehouse.sqlite3` (~1.68 GB) | derived, rebuildable (`INSERT OR IGNORE`; re-ingest 2026-11-12 reported all-duplicates-ignored) | 82 membership-spell symbols; 2,777 observed sessions | derived from the above only |

No W3 module fetches anything; the quantlab package reads the warehouse
read-only. Pre-archive simulated decisions are labelled `RETROSPECTIVE` on
every snapshot; `VENDOR_RECONSTRUCTION` bars (post 2026-09-18) are excluded by
construction and never enter W3 windows.

## 2. Known gaps and how W3 treats them

- **2024-01-01 → 2024-06-20 MISSING_SPAN:** no official bars. W3 windows never
  bridge it: feature lookbacks containing archive session-gaps abstain
  (typed), and the span lies inside the quarantined holdout anyway, so no W3
  fold touches it.
- **2026-09-18 → present:** vendor-only; excluded by construction. Combined
  with "no sessions beyond today", this yields `NEW_SEALED_HOLDOUT_UNAVAILABLE`
  (see `wave3_forward_protocol.md`).
- **Weekend/holiday calendar:** sessions are the observed bar sessions
  (`warehouse.sessions`); nothing is stitched across a missing session
  (window consecutiveness is checked against the session index).

## 3. The revealed W2 holdout is QUARANTINED

- Window: **2024-06-21 .. 2026-09-17** (opened once in Wave 2; H1 reveal).
- W3 train/validation spans end **2023-12-31** — more than three months of
  embargo distance before the holdout starts.
- `quantlab.folds.make_folds` **raises** on any requested span intersecting
  the holdout; `tests/test_research_v3_quantlab.py` proves the refusal for
  both a partially and a fully overlapping span.
- No W3 feature, label, fold, model, challenge or artifact computation reads
  any session inside the window. W3 does not rename any previously seen
  period as a "new holdout"; with no fresh sealed window available, W3
  reports `NEW_SEALED_HOLDOUT_UNAVAILABLE` and hands Wave 4 the forward
  protocol.

## 4. Split definition (preregistered, fixed)

| Span | Sessions | Use |
|---|---|---|
| TRAIN | 2015-06-01 .. 2021-12-31 | fit (per expanding walk-forward fold) |
| VALIDATION | 2022-01-01 .. 2023-12-31 | walk-forward evaluation, 4 expanding folds, tiled non-overlapping |
| REVEALED_W2_HOLDOUT | 2024-06-21 .. 2026-09-17 | QUARANTINED — never used |
| NEW_SEALED_HOLDOUT | — | UNAVAILABLE → forward protocol |

- Folds are session-ordered expanding windows; validation folds tile the
  validation span exactly once (no overlap).
- **Purge:** a training row is dropped when its label `exit_session` reaches
  the validation span minus a **10-session embargo**
  (`quantlab.folds.purge_ok`; unknown/absent exits fail closed).
- **No same-close fill:** every label enters at the next-session OPEN after
  the decision instant (T00:15 IST of the next local day) — the decision
  close is never a fill (W1 engine semantics, reused unchanged).
- **Cadence:** weekly (last session of each ISO week) decision sessions for
  snapshots + h5/h20 labels; monthly (last session of month) for h60.

## 5. Feature/label eligibility state (measured by the orchestrator run)

**Totals.** 25,316 PIT feature snapshots (82 spell symbols, 2,777 observed
sessions; 448 weekly + 103 monthly decision sessions). 49,989 labels built
with the W1 `executable_label` engine (unchanged): **47,852 ADMISSIBLE
(95.7%)**, **163 `DATA_BLOCKED_ACTION_WINDOW`** (action-shaped raw-price
discontinuity inside the label window — excluded from every statistic,
contamination disclosed), **1,974 `NO_LABEL`** (NO_FILL / NO_DECISION_BASELINE
— history or exit horizon unavailable; fail-closed, never guessed through).
72 model runs (18 combos × 4 folds), **0 failures**.

**Per-fold validation samples** (admissible rows available to each fold's
predictions): wf1 1,250 · wf2 1,301 · wf3 1,300 · wf4 1,350 weekly rows
(5,201 pooled across folds at weekly cadence; ≈1,177–1,202 per combo at
monthly h60). Training rows per fold (h5): 16,242 → 17,516 → 18,789 → 20,063
(expanding); rows dropped for purge/embargo or label-ineligibility are counted
per run in `wave3_model_comparison.json` (`runs[].n_excluded_rows`,
`runs[].n_train_rows`).

**Membership provenance mix** (active spell at the mid-validation probe
2022-06-30): **16 strict (press-release) + 34 weak (snapshot_floor) = 50
members** — the weak spells are backward-walk upper bounds disclosed by the
W1 warehouse, never presented as verified. Overall, 33 of the 82 spell
symbols carry at least one strict spell and 49 carry only weak spells; every
label row inherits the strictness of its active spell (`membership_strict`)
and the CC BY 4.0 attribution rides on every spell row.

See `wave3_model_comparison.json` (`labels`, `runs`, `folds`) for the exact
machine-readable counts produced by the run; the numbers in that file are the
authority if they ever differ from prose.

## 6. Leakage checks performed

1. Every feature reads only bars with `available_at <= decision_ts`
   (W1/W2 rule; bisect-gated in the inherited `PitPanel`).
2. A decision after a completed close can never fill at that close
   (entry = next eligible observation; fixture-tested).
3. Action-shaped discontinuities (close/prev_close outside [0.65, 1.54])
   inside a feature's lookback window refuse the feature (typed abstain,
   never guessed through).
4. Label windows containing such discontinuities are typed
   `DATA_BLOCKED_ACTION_WINDOW` and excluded from statistics (contamination
   stays disclosed inside gross paths — no selective cleaning, no upward
   bias).
5. Train-only standardization: ridge/logistic fit their scaler on training
   rows only; validation rows are transformed with the training scaler
   (fixture-tested).
6. No imputation anywhere: abstaining features are named exclusions for
   complete-row families and explicit NaN for the NaN-tolerant learner.
7. Sector-relative features are never emitted (no verified as-of sector map).

## 7. Inherited runtime test counts at handoff

- Dev repo full suite: **573 passed** (543 pre-existing + 30 new quantlab).
- Production-synced repo: quantlab tests **30 passed**; full suite 594 passed
  with 5 pre-existing failures in user-modified gateway/integration tests
  (live-credential and uncommitted-change dependent; no research_v3 path
  involved).
