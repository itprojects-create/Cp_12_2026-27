# Wave 3 — Acceptance Report

Date: 2026-11-13 · Research-only · **no commits made** · no order authority
granted or used · no third-party data fetched.

## 1. What was built (engineering)

New subpackage `backend-extension/quantplus_intelligence/research_v3/quantlab/`
(8 modules, hermetic, reusing W0 economics + W1 warehouse/labels + W2 lab
contracts/journal unchanged — no second accounting or PIT implementation):

| Module | Role |
|---|---|
| `contracts.py` | `FeatureSnapshot` / `ReturnLabel` / `TrainFold` / `ModelRun` typed records; canonical `compute_run_id` (family, config, **horizon**, fold, feature_hash, label_hash — timestamps excluded) |
| `features.py` | `FeaturePanel`: PIT-gated 12-feature snapshots (bisect on `available_at <= decision_ts`), discontinuity abstention, volume/value history, spell-provenance lookup, official TRI read |
| `labeling.py` | `build_label(s)`: W1 `executable_label` + typed admissibility (ADMISSIBLE / DATA_BLOCKED_ACTION_WINDOW / NO_LABEL), contamination disclosure, `membership_strict` |
| `folds.py` | session-indexed expanding walk-forward folds, 10-session embargo, `purge_ok` fail-closed, **holdout quarantine raise** (`REVEALED_W2_HOLDOUT` 2024-06-21..2026-09-17) |
| `metrics.py` | day-clustered rank IC (ties averaged, thin days excluded + disclosed), Brier, MAE, quintile spreads |
| `models.py` | fixed preregistered configs: climatology 0.5, momentum rank (ret_60), reversal rank (−ret_5), ridge α=1.0 (train-only standardizer), logistic C=1.0, HGB (150/0.05/3/100, seed 7); batched predictions; complete-row vs NaN-tolerant exclusion |
| `adapter.py` | W2-journal integration (`SPEC_PREREGISTERED`/`RUN_REGISTERED`/`CHALLENGE_REGISTERED`), challenger battery glue, RESEARCH_ONLY candidate lists |
| `__init__.py` | exports |

Orchestrator `backend-extension/scripts/wave3_run_quantlab.py` (dev repo only —
W2 precedent: research DB lives in the dev repo; production sync = package +
tests, byte-verified).

## 2. Exact commands and test counts

| Command | Result |
|---|---|
| `python -m pytest tests/test_research_v3_quantlab.py -q` (dev) | **30 passed** |
| `python -m pytest tests -q` (dev, full) | **573 passed** (543 pre-existing + 30 new; 16.9 s suite) |
| `python -m pytest tests/test_research_v3_quantlab.py -q` (production `D:\QP\agent-service`) | **30 passed** |
| `python -m pytest tests -q` (production, full) | **594 passed, 5 failed — all 5 pre-existing** in user-modified (M) gateway/integration files (`test_gateway_limits.py`, `test_stock_integration.py`): "all configured API keys were rejected" live-credential failures; no research_v3 import path involved; documented, not fixed |
| `python scripts\wave3_run_quantlab.py` (real data) | exit clean; log shows panel → snapshots → labels → 72 runs → artifacts, **0 run failures** |

Production sync verification: `Get-FileHash` over all 8 package modules + the
test file — byte-identical pairs (e.g. `contracts.py` = `20980963FA46…`,
test file = `18B320DBCCD4…` on both sides).

## 3. Real-data run (facts, not estimates)

- Panel: 82 spell symbols, 2,777 sessions; 25,316 snapshots; 448 weekly +
  103 monthly decision sessions.
- Labels: **49,989** → 47,852 ADMISSIBLE (95.7%) · 163
  `DATA_BLOCKED_ACTION_WINDOW` · 1,974 `NO_LABEL`.
- Runs: 18 combos × 4 folds = 72, **0 failures**; folds wf1–wf4 expanding,
  validation tilts tile 2022-01-03..2023-12-29 exactly once, embargo 10.
- Journal: 18 `SPEC_PREREGISTERED` + 72 `RUN_REGISTERED` + 18
  `CHALLENGE_REGISTERED` per full registration; chain verified intact.
- Holdout: never touched; fold builder refuses intersecting spans (tested).

## 4. Determinism evidence (rerun)

Two additional full orchestrator runs of the final code were executed
back-to-back on the same warehouse (run2, run3):

- `feature_hash` and `label_hash` identical across run1/run2/run3
  (`634b3669a3aacde6…`, `0053df3de4d04032…` — full values in the manifest).
- All id-independent content is **byte-equal** between run1 and the final
  run: 18 metrics dicts, label counts, fold spans, snapshots (25,316),
  failures (0), candidates sample (40 rows), and all 18 challenge dicts
  once the pooled `run_id` field is excluded (the only field that changed —
  see below); the contracts file differs only in `generated_at`.
- Run identity scheme was corrected once during W3 (run1 → run2): the
  **horizon** was added to `compute_run_id` because run1's ids collided across
  horizons (72 runs → 24 distinct ids; h5/h20/h60 of the same family+fold
  shared an id despite different fitted prediction sets). Final ids are
  1:1 with (family, horizon, fold) — 72 distinct ids. Old-scheme ids never
  appear in the new journal chain.
- Run2 ≡ run3: the shipped `wave3_research_journal.jsonl` contains **two
  chained full-run registrations (216 events = 36 + 144 + 36); the second
  108 semantic tuples (event, strategy_id, result_id, verdict) are identical
  to the first 108**, and `chain_valid = true` across the whole file. The
  journal is therefore itself the rerun-determinism record (W2 precedent:
  ids stable across independent runs).

(Comparison executed by a read-only script over the run1 backup and the final
artifacts; backups under the session temp dir, not in the repo.)

## 5. Artifact inventory (all in `reports/alpha_v3_1/`)

| Artifact | Content |
|---|---|
| `wave3_input_data_and_split_audit.md` | inputs + hashes, gaps, quarantine, split definition, eligibility counts, leakage checks |
| `wave3_model_comparison.json` | machine-readable: windows/folds/labels/72 runs/18 metrics/18 challenges/candidates/verdict rules |
| `wave3_model_comparison.md` | side-by-side all 18 combos incl. negative results, GROSS/NET/BENCH discipline |
| `wave3_challenger_report.md` | permutation percentiles, sensitivity spreads, thinned-t caveats, 9 REJECTED / 9 RESEARCH_DIAGNOSTIC |
| `wave3_economics_and_actions_blockers.md` | typed blockers + remediation checklist (actions, fees, basis, span, sector, clean-window policy) |
| `wave3_forward_protocol.md` | `NEW_SEALED_HOLDOUT_UNAVAILABLE` + preregistered forward freeze |
| `wave3_feature_label_contracts.json` | feature vector + label contract + hashes |
| `wave3_research_journal.jsonl` | append-only hash chain (two chained registrations) |
| `wave3_journal_status.json` | chain status snapshot |
| `wave3_reproducibility_manifest.json` | artifact + code-module sha256s, feature/label hashes |

sha256 for every artifact and module is in
`wave3_reproducibility_manifest.json` (md hashes appended post-run, disclosed).

## 6. Verdicts

- **Engineering: PASS.** Leakage attempts fail closed; quarantine enforced;
  purge/embargo tested; train-only standardization; typed failures; negative
  control at chance; 30/30 tests in both repos; deterministic ids.
- **Evidence: RESEARCH_DIAGNOSTIC / PARTIAL_DATA_BLOCKED.** Momentum
  REJECTED at every horizon (negative IC, perm percentile 0–1%); h20 fitted
  cluster survives the permutation gate (logistic 100th, ridge 100th, hgb
  98.5th) but thinned-t is only 1.60–1.77 over 26 non-overlapping days —
  suggestive, not significant; h60 rejected everywhere (24 monthly days).
  **NET_ABSOLUTE and BENCHMARK_RELATIVE: DATA_BLOCKED for the whole span**
  (fee schedule effective 2026-03-01; raw fills vs TRI basis mismatch).
  **NEW_SEALED_HOLDOUT_UNAVAILABLE** → forward protocol preregistered.
  **Nothing promoted to TRADE/PROFITABLE; no order authority.**

## 7. Handoffs to Wave 4

1. Frozen deterministic baselines + the forward protocol (seal → preregister
   → run → challenge → reveal) for Jev/Mercury comparison.
2. The typed-blockers checklist (verified corporate-actions ledger with PIT
   availability; dated fee history; adjusted fills + same-basis benchmark;
   2024 H1 official bars; sector map) — each unblocks a specific
   DATA_BLOCKED metric.
3. Production repo already carries the byte-identical package + tests; the
   research DB and orchestrator remain dev-repo (W2 precedent).
