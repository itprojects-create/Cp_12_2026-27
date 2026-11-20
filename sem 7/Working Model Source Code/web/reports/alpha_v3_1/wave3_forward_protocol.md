# Wave 3 — Forward Protocol (future untouched holdout)

`NEW_SEALED_HOLDOUT_UNAVAILABLE` is the honest status of Wave 3:

- The **revealed W2 holdout (2024-06-21 .. 2026-09-17) was opened once** in
  Wave 2. It is permanently disqualified as a fresh holdout for W3 and was
  never touched by any W3 computation (the fold builder refuses any span that
  intersects it; tests prove the refusal).
- A fresh sealed window would have to come from data **after 2026-09-17**.
  Bars after that date are vendor-only (`VENDOR_RECONSTRUCTION`, excluded by
  construction), and sessions after ~today (2026-11-13) do not exist yet.
- Therefore W3 evidence is limited to **purged walk-forward development
  diagnostics** (train 2015-06-01..2021-12-31, validation 2022-01-01..2023-12-31)
  — all labelled `RESEARCH_DIAGNOSTIC` — and a **prospective forward
  protocol** defined now, before any forward data exists.

## The pre-registered freeze (nothing below may be amended after forward data
## starts arriving; amendments require a new version and a new seal)

1. **Data cutoff rule.** The forward window starts at the first session for
   which an **OFFICIAL_EXCHANGE_RECORD** bar (post-2026-09-17 archive or a
   newer official source, source-hashed) becomes available in the W1
   warehouse. Vendor snapshots never enter the forward window.

2. **Seal before exposure.** When forward data begins, the W2
   `ResearchJournal` records `HOLDOUT_SEALED` for each frozen spec (strategy
   id `wave3.<family>.h<h>`, version 1) **before** any forward computation
   runs. Sealing happens once per spec version; `reveal_holdout` may be
   called at most once per version (journal-enforced).

3. **Frozen artifacts.** The candidate set is exactly the W3 baseline suite
   with its preregistered fixed configurations (`wave3_model_comparison.json`
   `verdict_rules` + `wave3_feature_label_contracts.json`):
   climatology 0.5, momentum rank (ret_60), reversal rank (−ret_5), ridge
   (alpha 1.0, train-only standardization), logistic (C 1.0), HGB
   (max_iter 150, lr 0.05, depth 3, min_samples_leaf 100, seed 7). **No
   hyperparameter may be re-tuned against forward data.** Any change creates
   `version 2` with a fresh seal and re-preregistration.

4. **Feature/label freeze.** The 12-feature PIT vector, weekly decision
   cadence, h5/h20 horizons (h60 monthly), next-session-open entry and
   h-session-close exit, and the [0.65, 1.54] discontinuity gate are frozen
   as shipped. New features are a new version.

5. **Decision rule (pre-registered selection).** After the sealed window
   accumulates at least **26 weekly decision sessions** (~6 months) of
   admissible labels, evaluate each candidate once:
   - primary metric: pooled **day-clustered rank IC** on the sealed window
     (day-level t-stat; names within a day are one correlated group);
   - promotion requires: mean day-clustered IC percentile ≥ **90** against
     within-day permutations on the sealed window, **and** IC > 0 in a
     majority of fold-equivalent contiguous sub-spans, **and** no leakage
     challenge failure;
   - NET_ABSOLUTE and BENCHMARK_RELATIVE on the forward window remain typed
     `DATA_BLOCKED` until the actions/fee/basis remediations land; a
     promotion to `RESEARCH_CANDIDATE` still confers **no** order authority
     (Jev/Mercury integration is Wave 4 and remains RESEARCH_ONLY until the
     governance layer decides otherwise).
   - If the sealed window cannot accumulate 26 admissible weekly sessions of
     official data, the verdict is `INCONCLUSIVE` — never a pass.

6. **One reveal.** Evaluating the sealed window ends it. If a candidate is
   promoted, its evaluation period is retired and the protocol re-seals a new
   window for monitoring. Previously revealed windows are never renamed as
   fresh.

7. **Observability without reopening W2's holdout.** Forward paper evidence
   accrues in the existing V2/agent paper book and the W2 journal chain; the
   W2 holdout's own numbers remain what they were (H1 gross −19.53% in the
   contiguous 2024-06..2026-08 reveal, placeo 8th percentile) — audit-only
   context, never a W3 selection signal.

## What Wave 4 inherits

- Frozen, deterministic baselines (this wave) to compare Jev/Mercury against.
- The journal + manifest discipline (seal → preregister → run → challenge →
  reveal, hash-chained).
- The typed blockers list (`wave3_economics_and_actions_blockers.md`) whose
  resolution converts `DATA_BLOCKED` economics into evaluable ones.
