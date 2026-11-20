# Prereg: Day-5 biting eval (NEWW_PLAN)

**Written:** before any Day-5 code or measurement. Deterministic except the
queued Devil-off ablation (LLM, blocked on token cap — harness only today).

## 1. Trial registry (return/Sharpe claim family on 2021-2026)

Every configuration ever measured on this window for a return/Sharpe claim:

| # | Config | Artifact | Sharpe |
|---|---|---|---|
| 1 | v1 (136% exposure bug) | prereg_core_v2_exposure.md | 0.80* |
| 2 | v2 | core_backtest_20261006.json | 0.698 |
| 3 | v3 narrow | core_backtest_v3.json | 0.705 |
| 4 | v3 broad (dust) | core_backtest_v3_broad.json | 0.853 |
| 5 | v3+veto overlay | overlay_vs_core_20261007.json | 0.776 |
| 6 | v4 narrow | core_backtest_v4_nifty50.json | 0.687 |
| 7 | v4 broad | core_backtest_v4_broad.json | 1.509 |
| 8 | paper narrow flat | paper_10L_nifty50.json | ~0.69** |
| 9 | paper broad flat | paper_10L_broad.json | ~1.51** |
| 10 | paper narrow env | paper_10L_nifty50_env.json | ~0.69** |

\* leverage-inflated, discarded. \*\* paper Sharpes inherit fractional runs.
K=10 trials. Agent direction evals (13+ reports) are a SEPARATE claim family
(accuracy, not Sharpe) — noted, not mixed.

## 2. Deflated Sharpe (Bailey–Lopez de Prado)

DSR(SR*) with SR* = headline max (1.509 broad; 0.776 shippable narrow),
T = 1420 days, skew/kurt from recomputed narrow daily series (measurement
re-run of the frozen rule — permitted, preregistered here), trials K=10 for
both (conservative: narrow shares the family). Broad daily recompute (391-name
fetch) deferred — broad DSR marked PENDING, which itself caps the 1.51 claim.
Benchmark SR0 = 0 (cash) AND reported vs buy-hold where available.

## 3. Perturbation suite (PC/CI/IDS, Profit-Mirage-adapted, documented)

On veto_fraction + positioning veto + apply_veto over synthetic grids with
±ε input noise (ε = 1% relative on numeric inputs, category flips excluded):
- PC (consistency) = fraction with unchanged binary call (veto<0.5 vs ≥0.5).
  Gate: PC ≥ 0.85 (a veto that flips under dust is not a rule).
- CI (confidence invariance) = 1 − std(output)/0.5, reported, NO gate
  (stability-vs-sensitivity tradeoff is documented, not legislated).
- IDS (input sensitivity) = mean|Δout| / mean|Δin| over perturbed pairs.
  Gate: IDS > 0 strictly (a memorized constant scores 0 and is flagged).
Constant-function control must yield PC=1.0, IDS=0 (suite validity check).
- **Amendment 1 (same day, post-first-run, gate misspecification — NOT a re-run
  of the published artifact):** IDS>0-strict fails stepwise veto tables that are
  locally flat BY DESIGN (thresholds stable under dust is robustness, and the
  PC gate already rewards it). Revised rule: continuous maps keep the IDS>0
  gate; stepwise tables are gated on PC ≥ 0.85 PLUS non-degeneracy
  (0 < fire_rate < 1 on the grid — fires sometimes, not always, not never).
  The published report's ids_gate:false stands as measured; the addendum
  records fire rates under the corrected gate.

## 4. Ablations

- veto-off vs veto-on: CITED from overlay_vs_core_20261007.json (0.705→0.776),
  not re-run (re-running = 11th trial for zero new information).
- Devil-off: harness implemented today (additive bypass flag, default off),
  execution QUEUED for funded window with exact command in report. Status is
  part of the verdict, not a footnote.

## 5. Friction matrix (Alpha-Illusion-adapted)

Cells: brokerage, STT, stamp, GST/SEBI, spread-per-tier, circuit non-fills,
token inference, slippage-beyond-spread, latency, corporate-action timing,
survivorship, model-level LLM leakage. Each: modeled|partial|unmodeled +
rupee estimate or magnitude bound or explicit reason. Latency = N/A with
justification (weekly rebalance). LLM-leakage = N/A for deterministic core
(immune by construction), APPLIES to agent evals (contaminated in LLM's favor,
still failed — stronger null).

## Gate

Day-5 exit = as-is report (JSON + verdict lines): narrow DSR number, perturbation
gates, friction table, ablation statuses, broad-DSR PENDING. Numbers that miss
gates are published, not re-run. Thresholds change only by amendment.
