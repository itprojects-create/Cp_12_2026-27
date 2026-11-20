# Baseline honest-analysis + M4 counter-trend guardrail — report

**Date:** 2026-10-06 · **Code:** `PROMPT_VERSION=m9` · **Gates:** frozen 2026-09-18, untouched
**Scope:** measurement + one code-level guardrail. No prompt/gate/contract changes.
**Tests:** 69/69 green (52 prior + 9 baselines + 8 market-trend).

---

## 1. The only "positive/PASS/profitable" result in the repo is oracle-tainted

`data/eval_report_20261005T182233Z.json` (prompt **m6**) reported **accuracy 1.000
(13/13), verdict PASS, PnL +0.1033**. All **24/24** of its session ids are present in
`data/oracle_tainted_sessions_DO_NOT_USE.json`. It is the Oracle-Patch run — 100%
accuracy because the future returns were fed into the orchestrator. It was **not**
covered by the integrity audit's session quarantine (which removed the DB rows), so the
report file was still sitting in `data/` and was still matched by the `eval_report_*.json`
glob that `scripts/diagnose_calibration.py` pools.

**Action:** renamed to `data/oracle_tainted_eval_report_20261005T182233Z_DO_NOT_USE.json`
so no glob can pool it. The report is preserved, not deleted.

**Implication for the goal:** the requested "positive, profitable" outcome already exists
on disk — and it is exactly the fabrication the integrity audit purged. Resurrecting or
imitating it would not make the agent profitable; it would make the report lie.

## 2. Honest baselines: the agent never beats a trivial constant rule

New `app/eval/baselines.py` scores the agent and constant policies through the same path,
with an exact two-sided binomial p-value and a seeded bootstrap CI. Now embedded in every
future report (`run.py` → `baselines` key). Full output: `data/baseline_analysis.json`.

Across the **11 non-tainted** reports (all decisive rows):

| set | agent acc | best constant | agent beats constant? |
|---|---|---|---|
| v1-2023-2024 (×4) | 0.333 / 0.333 / 0.500 / 0.333 | always_long 0.583 | **No** (all) |
| v5-2025-disjoint (×4) | 0.385 / 0.385 / 0.231 / 0.077 | always_long 0.615 | **No** (all) |
| v3rd-2026-clean (×3) | 0.176 / 0.059 / 0.176 | always_short 0.588 | **No** (all) |

- **`beats_best_constant = False` on 11/11 reports.** The agent's *selection* has
  negative skill: it under-performs "always long" in the 2025 up-tape and "always short"
  in the 2026 down-tape.
- Where `beats_chance = True` (v3rd), it is because the agent is **reliably wrong**
  (3/17, p=0.013; 1/17, p=0.000) — it buys into a falling market.
- The "best constant" flips with the sample's market direction, i.e. it is beta/drift,
  not a stable edge. No policy here shows a robust, significant edge.

## 3. M4 counter-trend guardrail (genuine, non-overfit improvement)

**Rule** (`app/data/regime.py::classify_trend`/`market_trend_at`, enforced in
`trader_risk.run_pm`, wired in `graph.py`): **do not take a LONG into a confirmed index
(^NSEI) downtrend, nor a SHORT into a confirmed uptrend.** Symmetric, PIT-safe (uses only
bars up to `as_of`), deterministic, applied after all LLM reasoning, audited in
`rationale`. RANGE/UNKNOWN never gate.

Motivation is the §2 finding: the agent's negative skill comes from taking counter-trend
positions. `PROMPT_VERSION` bumped m8→m9 so no cached session reuses an old decision.

**Offline counterfactual** (`scripts/counterfactual_trend_gate.py`, in-sample, 0 tokens)
replaying the recorded decisions through the gate:

- PnL improved in 9/11 reports; **pooled unit-book PnL −0.0650 → −0.0350** (delta **+0.0300**).
- Most striking: the m8 v3rd run **−0.0092 → −0.0000** (the losing longs were blocked).
- **Accuracy unchanged** (blocking a wrong trade is still "wrong" on a decisive label).

**Honest verdict:** the guardrail is a real risk improvement (it roughly halves the loss
on the sets run) but it does **not** create an edge and does **not** turn a FAIL into a
PASS. Accuracy stays 0.176 on v3rd. In-sample, and it will block some correct
counter-trend calls.

## 4. What "positive and profitable" would actually require

The evidence says daily-direction edge is not present in this system (consistent with the
prior quant-plus null result). The only honest paths to a defensible positive number are:
1. **Trade with the index trend** — the best constant conditioned on regime already scores
   ~0.58–0.62 (> the 0.55 gate); a system that takes direction FROM the regime and lets the
   LLM only size/veto within it would likely clear the accuracy gate. Must be validated
   out-of-sample before any claim (it is otherwise curve-fit to sample drift).
2. **Reframe the target** — no-edge detection / risk control / calibration, where the
   system can plausibly hold an edge.
3. **Power** — n=12–17 decisive cannot distinguish skill from luck; a claim needs a large
   fresh blind set.
