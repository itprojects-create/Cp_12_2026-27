# Wave 3 — Challenger Report (adversarial battery over the baseline ladder)

Scope of every challenge below: **pooled walk-forward validation predictions
from all 4 folds** (train/validation only; scope string recorded in each
challenge). Machine-readable authority: `wave3_model_comparison.json` →
`challenges` (this document paraphrases it). Every verdict honours the
preregistered rule: **permuted-IC below the 90th percentile → REJECTED**;
diagnostics-only evidence → RESEARCH_DIAGNOSTIC; nothing promotes to
TRADE/PROFITABLE, and no fresh sealed holdout exists
(`NEW_SEALED_HOLDOUT_UNAVAILABLE`).

## 1. Battery design

- **Permutation noise control** (`permuted_ic_noise`): 200 within-day
  permutations (seeded `wave3.<family>.h<h>`), day-clustered observed IC vs
  the null distribution; PASS requires ≥ 90th percentile.
- **Lookback / regularisation sensitivity** (`sensitivity_lookback`):
  momentum — IC under ret_20/ret_60/ret_120; ridge — IC under
  alpha 0.1 / 1.0 / 10.0 (pooled walk-forward recomputation each time).
  PASS = spread small and sign stable; DISCLOSED = reported without a pass.
- **Cost sensitivity** (`cost_sensitivity`): **INCONCLUSIVE for all 18
  combos** — the only verified fee schedule (`nse-cm-delivery-2026-03-01`)
  does not cover any train/validation window; no net months exist, so no
  cost verdict can be earned. Typed, never estimated.
- **Holdout integrity** (`holdout_integrity`): **PASS for all 18** — the
  quarantined revealed W2 holdout 2024-06-21..2026-09-17 was never used for
  training, validation, selection or challenge evaluation (fold builder
  refuses intersecting spans; tests prove the refusal).

## 2. Per-combination outcomes (all 18)

| Combo | Observed IC | Perm null median | Perm pct | Verdict on IC check | Final verdict |
|---|---|---|---|---|---|
| climatology@h5 | n/a (constant) | — | — | INCONCLUSIVE (no rank pairs) | RESEARCH_DIAGNOSTIC |
| climatology@h20 | n/a (constant) | — | — | INCONCLUSIVE | RESEARCH_DIAGNOSTIC |
| climatology@h60 | n/a (constant) | — | — | INCONCLUSIVE | RESEARCH_DIAGNOSTIC |
| momentum@h5 | −0.046944 | −0.000711 | 0.000 | FAIL | **REJECTED** |
| momentum@h20 | −0.051300 | −0.000299 | 0.000 | FAIL | **REJECTED** |
| momentum@h60 | −0.065194 | +0.001913 | 0.010 | FAIL | **REJECTED** |
| reversal@h5 | +0.084335 | −0.000312 | 1.000 | PASS | RESEARCH_DIAGNOSTIC |
| reversal@h20 | +0.034582 | +0.000922 | 0.980 | PASS | RESEARCH_DIAGNOSTIC |
| reversal@h60 | −0.002791 | −0.001100 | 0.495 | FAIL | **REJECTED** |
| ridge@h5 | −0.018485 | +0.000651 | 0.100 | FAIL | **REJECTED** |
| ridge@h20 | +0.045941 | −0.000039 | 1.000 | PASS | RESEARCH_DIAGNOSTIC |
| ridge@h60 | −0.013801 | −0.004367 | 0.345 | FAIL | **REJECTED** |
| logistic@h5 | +0.009002 | −0.001508 | 0.765 | FAIL | **REJECTED** |
| logistic@h20 | +0.050879 | −0.000050 | 1.000 | PASS | RESEARCH_DIAGNOSTIC |
| logistic@h60 | −0.047412 | +0.001981 | 0.075 | FAIL | **REJECTED** |
| hgb@h5 | +0.021505 | −0.001595 | 0.935 | PASS | RESEARCH_DIAGNOSTIC |
| hgb@h20 | +0.036751 | −0.002901 | 0.985 | PASS | RESEARCH_DIAGNOSTIC |
| hgb@h60 | −0.019341 | −0.002873 | 0.295 | FAIL | **REJECTED** |

**Tally: 9 REJECTED / 9 RESEARCH_DIAGNOSTIC / 0 promoted.** The negative
control (climatology) earns no IC pass and no promotion — the correct
noise-floor behaviour.

## 3. Sensitivity disclosures

| Combo | Variants (IC) | Spread | Battery status |
|---|---|---|---|
| momentum@h5 | ret_20 −0.052241 · ret_60 −0.046944 · ret_120 −0.066913 | 0.0200 | PASS (sign stable, all negative) |
| momentum@h20 | ret_20 −0.035382 · ret_60 −0.051300 · ret_120 −0.085334 | **0.0500** | DISCLOSED (magnitude moves, sign never flips) |
| momentum@h60 | ret_20 −0.057037 · ret_60 −0.065194 · ret_120 −0.093175 | 0.0361 | DISCLOSED |
| ridge@h5 | α=0.1 −0.018466 · α=1.0 −0.018485 · α=10 −0.018595 | 0.0001 | PASS |
| ridge@h20 | α=0.1 +0.046004 · α=1.0 +0.045941 · α=10 +0.045891 | **0.0001** | PASS (α-plateau) |
| ridge@h60 | α=0.1 −0.013548 · α=1.0 −0.013801 · α=10 −0.015121 | 0.0016 | PASS |

Reading: the momentum negative is a property of the signal family, not of one
lookback; the ridge h20 positive is not an artefact of the α choice
(plateau within 1.1e-4 IC).

## 4. Honest caveats on the surviving diagnostics

1. **Thinned non-overlapping t-stats are modest**: on windows thinned to
   genuine non-overlap (h20: every 4th week → 26 days; h60: every 12th month
   → 2 days), the survivors' t-stats are +1.60 (ridge), +1.77 (logistic),
   +0.60 (hgb) over 26 days. Suggestive, not significant; h60 t is
   unreliable (2 days) and is disclosed, never quoted as evidence.
2. **Gross, rank-based, and unhedged** — all ICs are vs same-day raw-fill
   gross returns; NET and BENCHMARK_RELATIVE remain DATA_BLOCKED
   (fee schedule effective 2026-03-01; raw-fills-vs-TRI basis mismatch), so
   no cost or benchmark claim is made anywhere.
3. **Multiple-comparison exposure**: 18 combos were challenged; the three
   strongest h20 diagnostics (logistic/ridge) sit at the 100th percentile but
   the battery is per-combo — the forward protocol (§5 of
   `wave3_forward_protocol.md`) is the pre-registered out-of-sample test,
   and the sealed-window rule (≥ 26 admissible weekly sessions, day-clustered
   IC ≥ 90th percentile, majority of sub-spans positive) is what can promote
   a candidate — nothing in this wave can.
4. **Candidate sample is final-fold only** (disclosed in the artifact):
   `candidates_sample` lists top-10 momentum/ridge @h20 names from wf4 —
   every row `authority=RESEARCH_ONLY`; rows with `in_admissible_labels=false`
   (e.g. TMPV) are abstention disclosures, not tradeable candidates.
5. **Pooled identity**: each challenge registers against the pooled run id
   `compute_run_id(family, config, wf4, feature_hash, label_hash + "|pooled4",
   horizon)` — the fold count suffix keeps pooled identities distinct from
   single-fold run ids.

## 5. Verdict

The adversarial battery **rejects 9 of 18 combinations outright** (all
momentum horizons; all fitted families at h5/h60; reversal at h60) and leaves
9 as RESEARCH_DIAGNOSTIC (climatology's typed-INCONCLUSIVE IC + designed
noise floor; reversal h5/h20; ridge/logistic/hgb h20; hgb h5). Combined with
Wave 2's revealed-holdout history (H1 gross −19.53%, placebo 8th percentile),
the honest state is: **no demonstrated gross edge survives at h60, momentum
is consistently counter-productive, and the h20 cluster is a development
diagnostic awaiting the forward protocol — with zero order authority.**
