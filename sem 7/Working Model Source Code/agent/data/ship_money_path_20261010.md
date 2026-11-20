# Ship note — money path = deterministic core; LLM = veto/resize/explainability

**Date:** 2026-10-10 · **Tests:** full suite green (see final run) · **Contract:** additive only
**Related:** `data/prereg_v4_trend_direction.md` (H1), `data/baseline_and_m4_report_20261006.md`,
`data/core_and_h1_report_20261006.md`, `data/prereg_overlay_retry.md`, `data/eval_v7_run.log`

## 1. Decision (evidence-driven)

The single-name LLM session pipeline has **no demonstrated directional edge**, and this
is now measured on three independent axes:

| evidence | result |
|---|---|
| 11 clean eval runs (`data/baseline_analysis.json`) | `beats_best_constant = False` **11/11** |
| Deterministic index-trend direction, out-of-sample (H1) | accuracy **0.111** vs best constant 0.556 → FAIL |
| Best constant itself flips with the sample's market leg | it is **beta/drift**, not a stable edge |

The only audited **positive** number in the repo is the deterministic momentum core:

| core | CAGR (after costs) | Sharpe | MaxDD |
|---|---|---|---|
| v2 | +6.15% | 0.698 | 16.35% |
| **v3 (shipped)** | +5.25% | **0.705** | **12.46%** |

Therefore, per the pre-registered H1 decision rule ("FAIL → stop iterating on direction"),
the **money path is the deterministic core** and the **LLM is demoted** to a
veto / resize / explainability layer. The LLM never originates direction and never
increases size.

## 2. What is enforced in code

`app/core/overlay.py::llm_overlay_size(core_size, core_direction, llm_action, llm_size)`
is the code-level guarantee of that contract (unit-tested in
`tests/test_money_path_boundary.py`):

- core target `<= 0` or `flat` → `0.0` (nothing to overlay);
- LLM action **opposite** the core direction → `0.0` (**veto, never a flip**);
- LLM action **hold** (abstain) → `core_size` (an uncertain LLM must not silently
  kill every core trade — the m11 always-hold failure mode);
- LLM action **agrees** → `min(core_size, llm_size)` (**resize down only**) via
  the existing `apply_veto` contract: `0 <= final <= core_size`, asserted.

## 3. What the live money path is (precise)

- The operational paper/fill path is `scripts/paper_trade_10L.py`, which replays the
  frozen `run_core_v4` rule with a real share ledger and a **zero-LLM** decision path
  (the deterministic `veto_fraction` whipsaw filter is the only overlay wired there).
  It carries a shadow-equity cross-check against `run_core_v4().eq_curve` (<1e-9) so
  the ledger cannot silently drift.
- The API's `POST /api/v1/sessions` still runs the full LLM pipeline. Under this ship
  that output is **research / explainability**, not a money instruction; `llm_overlay_size`
  is the designated composition point for any future integration that lets an LLM
  decision touch a core target.

## 4. Honest limitations

- `llm_overlay_size` is enforced and tested, but **no live caller composes an LLM
  decision onto a core target yet** — the live paper path is deterministic (zero LLM)
  and therefore already immune by construction. The boundary exists so that any future
  integration cannot violate the contract.
- `DIRECTION_POLICY` default remains `"llm"` for the **research** pipeline; it does not
  place the LLM on the money path.
- Survivorship bias in the backtest universe is disclosed and unchanged.
- The m12 evidence-grounding fix (`data/prereg_manager_evidence.md`) and the fresh v7
  read (`data/prereg_v7_2026h2.md`) test whether grounding moves the LLM's *research*
  quality; they do not change this money-path decision.
