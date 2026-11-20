# Trend Core v2 — Walk-Forward Result + H1 Verdict

**Date:** 2026-10-06 · **Code:** `PROMPT_VERSION=m9`, `DIRECTION_POLICY` restored to `llm` after H1
**Artifacts:** `data/eval_report_20261006T123319Z.json` (H1), `data/core_backtest_20261006.json` (core v2)
**Pre-registrations:** `data/prereg_v4_trend_direction.md` (H1), `data/prereg_core_v2_exposure.md` (amendment 1)
**Tests:** 87/87 green (`tests/test_core.py` 12 new: no-lookahead invariance, gross-cap, costs)

---

## 1. H1 (trend-direction policy) — FAIL, officially recorded

Per the pre-registered rule (`prereg_v4_trend_direction.md`, written before the
blind set was touched): ran the remaining 9/24 scenarios on `v4-2022-blind`
under `DIRECTION_POLICY=trend`; 15/24 replayed from cache at zero cost.

| metric | value | gate |
|---|---|---|
| n_decisive | 9 | ≥8 ✓ |
| accuracy | **0.111** (1/9) | ≥0.55 ✗ |
| no-edge hold | 0.200 | ≥0.40 ✗ |
| trade rate | 0.625 | ✓ |
| PnL | −0.0076 | — |
| beats best constant | **False** (always_long 0.556) | ✗ |

The trend rule genuinely fired UP through the Aug–Dec 2022 leg (13 buys), but
name-level 20d outcomes were flat/choppy → whipsaw. **Decision rule outcome:
FAIL → stop iterating on direction, reframe per plan.** Note: this is the third
independent confirmation (11 prior runs, H1) that LLM/trend direction selection
has no edge on 20d horizons.

`DIRECTION_POLICY` restored to `llm` (repo default) after the run; the H1 cfg
hash keeps those sessions isolated for the audit trail.

## 2. Core v1 → v2: the exposure bug and the honest fix

- **v1 (frozen rule as coded):** CAGR 17.7%, Sharpe 0.80, MaxDD 37.4%, avg gross
  exposure **135.8%** — unintended leverage; B&H beat it on every metric.
- **Amendment 1 preregistered** (`prereg_core_v2_exposure.md`): single change,
  Σ positions ≤ 100% (`GROSS_CAP=1.00`, proportional scale-down). Written as a
  correction to match the docstring's own rule — not a re-tune.
- **v2 (one re-run, recorded as-is):**

| metric | core v2 | equal-wt B&H (same biased universe) |
|---|---|---|
| CAGR (after costs) | **+6.15%** | +30.28% |
| Sharpe | 0.698 | 1.247 |
| MaxDD | **16.35%** | 17.21% |
| avg exposure | 49.7% | 100% |
| total costs | 6.4% of book | — |
| switches | 3968 | — |

Yearly (after costs): 2021 +14.4% / 2022 **−10.3%** / 2023 +15.3% / 2024 +12.3%
/ 2025 +1.3% / 2026 +4.1%.

## 3. Honest reading

- The core is **profitable after costs at unlevered scale** — a real, tradeable
  baseline now exists (v1's 17.7% was leverage, not skill).
- It still loses to B&H on this bull-heavy, survivorship-biased tape (disclosed
  bias inflates B&H too). Its claim is risk-adjusted: MaxDD 16.4% < B&H 17.2%,
  at half the average exposure — with the 2022 chop as its known weak spot.
- The 2022 loss (−10.3%) is exactly the whipsaw regime H1 flagged. That is the
  overlay's target, not "beat B&H everywhere."

## 4. Next: the LLM overlay (pre-register BEFORE evaluating)

Contract to preregister next: the overlay may only (a) VETO core entries it
judges falling-knives/whipsaw risk, (b) RESIZE within [0, core size]. It may
never add direction. Gate: overlay must beat core-v2 on Sharpe OR MaxDD over
the same window, evaluated on data the overlay prompt logic has never seen
(suggested: run core on 2021–2024, overlay develops on 2021–2024, joint test
2025–2026). If it fails, the LLM exits the money path and stays as the
explainability/no-edge-detection layer — still a defensible capstone.

## Appendix — reproduce

- `python scripts/run_core_backtest.py` (zero tokens) → `data/core_backtest_20261006.json`
- `python -m pytest tests -q` → 87 passed
- H1: `python scripts/run_eval_live.py --set v4` (already complete; do NOT rerun — one-shot discipline)
