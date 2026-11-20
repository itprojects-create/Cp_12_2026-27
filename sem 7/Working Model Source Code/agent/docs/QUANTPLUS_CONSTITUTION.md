# QUANTPLUS CONSTITUTION (human-readable; machine source: `app/governance/constitution.py`)

**Version:** v1 · **Status:** enforced by code + tests (`tests/test_governance.py`)

Central philosophy: **LLMs invent and investigate. Deterministic code trades.
Statistics judge. Forward evidence promotes. Risk systems control capital.**

## The 15 rules

1. **No LLM capital authority.** LLM output generates research hypotheses only. Direction,
   weight, quantity, exposure, leverage, stops, targets, entries, exits, allocation come
   from deterministic version-controlled code. Enforced by `FinalDecision.authority=
   RESEARCH_ONLY` + type-level invariant flags + boundary tests.
2. **No LLM upsizing.** Nothing LLM-originated may increase exposure beyond the deterministic
   engine. Temporary veto/resize use must be experimental, tagged, and measured against a
   no-LLM control (`apply_llm_overlay`, default OFF).
3. **Opinion is not alpha.** Confidence, consensus, votes, Devil approval are never
   profitability evidence. Only measured out-of-sample evidence counts.
4. **Hypotheses become deterministic code.** Hypothesis → proposal → validation →
   implementation → backtest → statistics → shadow → forward → promotion. No shortcut.
5. **Code cannot promote itself.** Candidates generate metrics; a separate deterministic
   judge promotes.
6. **History kills faster than it promotes.** Backtests reject aggressively; history alone
   never grants production authority; repeated optimization = contamination.
7. **Burned datasets stay burned.** Registry tracks exploratory/validation/burned/
   forward-only per dataset. Burned sets serve regression/falsification only.
8. **Forward evidence rules.** Post-historical survivors enter shadow/forward before champion.
9. **Compete against baselines.** Cash, benchmark, champion, simpler strategy,
   beta/exposure-matched control.
10. **CAGR is never enough.** Sharpe/Sortino/DD/CVaR/turnover/costs/concentration/beta/
    PBO/DSR/forward required.
11. **Net of reality.** Brokerage, taxes, costs, slippage, circuits, liquidity, cash drag,
    inference + data costs where applicable. Strategy economics and research economics
    reported separately.
12. **Research compute justifies itself.** Inference is an explicit per-hypothesis cost.
13. **Dead ideas stay dead.** Failures get fingerprints; rediscovery without new evidence
    is rejected via the corpse registry.
14. **Reproducibility.** Version + fingerprints + config + universe + timestamp reproduce
    any decision (experiment manifests + `reproduce_experiment.py`).
15. **No deployment claim without evidence.** Status labels only (`EXPERIMENTAL`,
    `BACKTEST_ONLY`, `HISTORICALLY_SURVIVED`, `SHADOW`, `FORWARD_VALIDATING`, `CHAMPION`,
    `RETIRED`, `DEAD`, …). `BACKTEST_POSITIVE` is not `PROVEN_ALPHA`.

## Safe-default configuration (§55)

`LLM_DIRECTION_AUTHORITY=false`, `LLM_MONEY_AUTHORITY=false`, `LLM_OVERLAY_ENABLED=false`;
research/foundry/memory/falsification/PIT/forward flags default true/required.
`DIRECTION_POLICY` selects the *research* decision path only.

## Promotion evidence ladder

`BACKTEST_ONLY` → `HISTORICALLY_SURVIVED` → `SHADOW` → `FORWARD_VALIDATING` → `CHAMPION`.
Gatesets are versioned (`GATESET_FROZEN_20260918`); new philosophy = new version + prereg,
never a silent threshold edit.
