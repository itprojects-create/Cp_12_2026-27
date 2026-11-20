# Evaluation gates (adopted 2026-10-06, prereg_model_data_wiring.md Step 4)

Two claim families, two gate sets. Mixing them was the original sin of the
V1 inflated claims (Model audit C1-H3); this file exists so it cannot recur.

## Family A — DIRECTION claims (any "the system predicts up/down/rank")

Adopted verbatim from the Model audit (configs/evaluation_gates.yaml lineage):

| Gate | Bar | Rationale |
|---|---|---|
| G1 Sharpe | ≥ 0.8 | Below this is noise with good marketing |
| G2 Deflated Sharpe | ≥ 0.95 | Bailey–López de Prado over ALL trials incl. failures |
| G3 PBO | ≤ 0.20 | Probability of backtest overfitting (see app/eval/dsr.py registry) |
| G4 Folds | ≥ 4 of 5 positive | No single-regime heroics |
| G5 Holdout | Sharpe > 0 AND CI > 0 | Certifiable, not point-estimated |

The old `accuracy ≥ 0.55` gate is RETIRED BY NAME for direction claims —
14 agent FAILs plus the certified N=477 null proved it measured nothing.
Any future direction attempt (LLM or ML) must preregister against G1–G5
before touching data. No prereg, no run, no exceptions.

## Family B — RISK / VETO claims ("the overlay cuts risk at matched exposure")

| Gate | Bar |
|---|---|
| Sharpe uplift vs frozen core, same window | > 0 (or MaxDD down ≥ 2pp) |
| Exposure drift vs core | within ±5pp (vetoes that just go flat fail) |
| Costs | fully loaded incl. tier spreads + token inference |
| Trial accounting | every configuration measured counts (see DSR registry) |

## Calibration scoping (the trap lesson, binding)

The Model audit proved isotonic calibration COMPRESSES ranked signals and
HURTS selection (Sharpe 1.317→0.875; calibrator discarded for ranking).
Therefore, in this repo, calibrated probabilities feed POSITION SCALE ONLY —
never rank, never selection, never veto-table structure. `app/memory/calibrate.py`
carries the SIZING-ONLY marker; any ranking use of its outputs is a
prereg-level violation requiring a new prereg AND a G1–G5 gate. No exceptions,
no matter how reasonable it looks.
