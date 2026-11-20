# Wave 3 — Model Comparison (baseline ladder, purged walk-forward)

Status: **RESEARCH_DIAGNOSTIC evidence only.** Every number below is gross,
rank-based, computed on walk-forward **validation folds only** (train
2015-06-01..2021-12-31, validation 2022-01-01..2023-12-31). The revealed W2
holdout (2024-06-21..2026-09-17) was never touched. Machine-readable authority:
`wave3_model_comparison.json` (this document paraphrases it; the JSON wins on
any mismatch).

## 1. Run setup (one orchestration, zero failures)

| Item | Value |
|---|---|
| Universe | NIFTY50 as-of spells (`warehouse.members_at`), 82 spell symbols |
| Observed sessions consumed | 2,777 (2015-06-01 .. 2023-12-29 + panel history) |
| Feature snapshots (decision-time, PIT-gated) | 25,316 |
| Labels (W1 `executable_label` engine, reused unchanged) | 49,989 total — **47,852 ADMISSIBLE**, 163 `DATA_BLOCKED_ACTION_WINDOW`, 1,974 `NO_LABEL` |
| Decision cadence | weekly (448 sessions) for snapshots + h5/h20; monthly (103) for h60 |
| Walk-forward folds | wf1..wf4 expanding, validation tilts tile 2022-01-03..2023-12-29 exactly once, embargo 10 sessions |
| Model runs | 18 family×horizon combos × 4 folds = **72 runs, 0 failures** |
| Fee/benchmark | schedule `nse-cm-delivery-2026-03-01`; benchmark `NIFTY50_TRI` (official) |

Fold spans (train end / validation span): wf1 2022-01-03 / 2022-01-03..2022-06-30 ·
wf2 2022-07-01 / 2022-07-01..2022-12-28 · wf3 2022-12-29 / 2022-12-29..2023-06-28 ·
wf4 2023-06-30 / 2023-06-30..2023-12-29.

## 2. Metric discipline (GROSS / NET / BENCHMARK_RELATIVE)

- **GROSS** columns are raw unadjusted-fill returns (`v3_gross_absolute`) —
  diagnostics only, never investor profit. Action-window-contaminated labels
  (163) are excluded from every statistic and stay disclosed.
- **NET** (`v3_net_absolute`): **DATA_BLOCKED** for the entire train/validation
  span — the verified fee schedule is effective 2026-03-01, so no historical
  window has net truth. Never filled with 0% or an estimate.
- **BENCHMARK_RELATIVE**: **DATA_BLOCKED_BASIS_MISMATCH** — fills are raw
  prices, the TRI benchmark is dividend-inclusive; the raw diagnostic number is
  disclosed separately in the JSON (`benchmark_relative_raw`), never presented
  as excess return.
- Rank IC: per-day Spearman between predictions and same-day admissible label
  gross returns, **day-clustered** t-stat (names within a day are one
  correlated group — never row-pooled).
- *Thinned non-overlap*: for h20 every 4th validation week (26 days), for h60
  every 12th month (2 days) — the honest-overlap t-stat. h5 is already
  non-overlapping at weekly cadence, so the full-sample t is the honest one.
- Brier: probability families only (climatology 0.5, logistic, HGB) vs
  sign(gross)>0.

## 3. Side-by-side results (all 18 combos)

Verdict keys: `RD` = RESEARCH_DIAGNOSTIC (passed the permutation battery on
validation folds), `REJ` = REJECTED (below the 90th percentile of the
within-day permutation null), `INC` = typed INCONCLUSIVE (constant predictor →
no rank-IC pairs).

| Combo | Rank IC | t (day-cl) | Days | Thinned IC (t, days) | Brier | MAE | Top−Bottom quintile gross | EW day-mean gross | NET | BENCH_REL | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| climatology@h5 | n/a (const) | — | 0 | — | **0.2500** | 0.4953 | +0.0029 (tie-order noise) | 0.0016 | DATA_BLOCKED | DATA_BLOCKED | INC on IC / RD |
| climatology@h20 | n/a (const) | — | 0 | — | **0.2500** | 0.4824 | +0.0096 (tie-order noise) | 0.0105 | DATA_BLOCKED | DATA_BLOCKED | INC on IC / RD |
| climatology@h60 | n/a (const) | — | 0 | — | **0.2500** | 0.4509 | +0.0268 (tie-order noise) | 0.0328 | DATA_BLOCKED | DATA_BLOCKED | INC on IC / RD |
| momentum_rank@h5 | **−0.0469** | −2.28 | 104 | — | — | 0.0990 | −0.0037 | 0.0016 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| momentum_rank@h20 | **−0.0513** | −2.47 | 104 | −0.0592 (−1.45, 26) | — | 0.1134 | −0.0092 | 0.0105 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| momentum_rank@h60 | **−0.0652** | −1.56 | 24 | −0.1885 (−3.60, 2) | — | 0.1549 | −0.0056 | 0.0328 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| reversal_rank@h5 | **+0.0843** | +4.16 | 104 | — | — | 0.0423 | +0.0092 | 0.0016 | DATA_BLOCKED | DATA_BLOCKED | **RD** |
| reversal_rank@h20 | **+0.0346** | +1.84 | 104 | +0.0378 (+1.06, 26) | — | 0.0712 | +0.0057 | 0.0105 | DATA_BLOCKED | DATA_BLOCKED | **RD** |
| reversal_rank@h60 | −0.0028 | −0.07 | 24 | −0.0238 (−0.40, 2) | — | 0.1255 | −0.0172 | 0.0328 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| ridge@h5 | −0.0185 | −0.97 | 104 | — | — | 0.0316 | +0.0009 | 0.0016 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| ridge@h20 | **+0.0459** | +2.52 | 104 | +0.0601 (+1.60, 26) | — | 0.0640 | +0.0131 | 0.0105 | DATA_BLOCKED | DATA_BLOCKED | **RD** |
| ridge@h60 | −0.0138 | −0.33 | 24 | −0.0074 (−0.22, 2) | — | 0.1188 | +0.0092 | 0.0328 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| logistic@h5 | +0.0090 | +0.49 | 104 | — | 0.2489 | 0.5039 | +0.0006 | 0.0016 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| logistic@h20 | **+0.0509** | +2.60 | 104 | +0.0672 (+1.77, 26) | 0.2454 | 0.5246 | +0.0137 | 0.0105 | DATA_BLOCKED | DATA_BLOCKED | **RD** |
| logistic@h60 | −0.0474 | −1.06 | 24 | −0.0459 (−1.54, 2) | 0.2439 | 0.5255 | +0.0132 | 0.0328 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |
| hgb@h5 | +0.0215 | +1.25 | 104 | — | 0.2492 | 0.5031 | +0.0023 | 0.0016 | DATA_BLOCKED | DATA_BLOCKED | **RD** |
| hgb@h20 | **+0.0368** | +2.18 | 104 | +0.0176 (+0.60, 26) | 0.2456 | 0.5241 | +0.0056 | 0.0105 | DATA_BLOCKED | DATA_BLOCKED | **RD** |
| hgb@h60 | −0.0193 | −0.52 | 24 | +0.0069 (+0.06, 2) | 0.2444 | 0.5239 | +0.0001 | 0.0328 | DATA_BLOCKED | DATA_BLOCKED | **REJECTED** |

Validation sample sizes (predictions / decision days): weekly families 5,201
(climatology, HGB), 5,095 (ridge, logistic — complete-row feature exclusion),
5,175 (momentum), 5,199 (reversal) over 104 weekly days; h60 ≈ 1,177–1,202
predictions over 24 monthly days.

## 4. What the numbers say (negative results included)

1. **Momentum is the strongest NEGATIVE result.** Negative rank IC at all
   three horizons (−0.047 / −0.051 / −0.065); the permutation percentile is
   0–1% — the IC is *worse than essentially every within-day permutation*.
   Top-minus-bottom quintile gross is negative everywhere. The lookback
   sensitivity spread (ret_20/60/120) is 0.050 at h20 — the sign is stable
   across lookbacks. This is consistent with Wave 2's momentum-flavoured
   strategies having no gross edge on the holdout, and with short-horizon
   NIFTY50 reversal tendency. Momentum is **REJECTED at every horizon**.
2. **Reversal is the best raw gross diagnostic** (h5 IC +0.084, t +4.16,
   permutation 100th percentile; h20 +0.035, 98th percentile) — but it
   REJECTS at h60 and, like everything else in this wave, carries no net
   economics and no order authority.
3. **The fitted families cluster at h20**: logistic +0.051 (t +2.60), ridge
   +0.046 (t +2.52), HGB +0.037 (t +2.18), all ≥ 98.5th permutation
   percentile. On the honest non-overlapping windows the t-stats are +1.60 to
   +1.77 over 26 days — **disclosed as suggestive, not significant**.
4. **Climatology (negative control) behaves as designed**: constant 0.5 →
   Brier exactly 0.2500 at every horizon (= chance), no rank-IC pairs (typed
   INCONCLUSIVE), and its "quintile spread" is tie-ordering noise. It passes
   nothing and demonstrates the battery's noise floor.
5. **h60 evidence is thin by construction** (24 monthly days; the thinned
   non-overlap is 2 days, so its t-stat is unreliable and disclosed as such).
   Every h60 fitted family REJECTS on the permutation gate.
6. **No combo is promoted.** Nothing here is TRADE, PROFITABLE, or cash:
   NET and BENCHMARK_RELATIVE are typed DATA_BLOCKED for the whole span, and
   no fresh sealed holdout exists (`NEW_SEALED_HOLDOUT_UNAVAILABLE`).

## 5. Determinism and provenance

- `run_id` = sha256 of canonical JSON over {family, config, **horizon**,
  fold-id hash, feature_hash, label_hash} — no timestamps. The horizon is part
  of the identity, so h5/h20/h60 runs of the same family+fold never collide.
- `feature_hash` `634b3669a3aacde6…`, `label_hash` `0053df3de4d04032…` (full
  values in `wave3_reproducibility_manifest.json`).
- Journal: the shipped `wave3_research_journal.jsonl` contains **two chained
  full-run registrations** (the rerun-determinism pair): 216 events =
  36 `SPEC_PREREGISTERED` + 144 `RUN_REGISTERED` + 36
  `CHALLENGE_REGISTERED`; the second registration's semantic tuples are
  identical to the first's and `chain_valid = true`
  (`wave3_journal_status.json`).
- A full independent rerun (same code, same warehouse) was executed to verify
  reproduction; see `wave3_acceptance_report.md` §determinism.
- Candidate sample (`candidates_sample`, momentum/ridge @h20 top-10s from the
  final fold wf4, scope disclosed): all entries `authority=RESEARCH_ONLY`;
  where `in_admissible_labels=false` (e.g. TMPV) the row is an abstention
  disclosure, not a tradeable candidate.
