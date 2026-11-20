# W4 — Paired financial ablation protocol (Arms A–F) + honest blockers

Generated: 2026-11-14T08:28:47.860313+00:00 · Authority: master prompt §W4.4, blueprint §10.4

## 1. Arms (preregistered, matched universe / dates / capital / fees / fills)

```
A: numerical price/factor core                    (W3 frozen control)
B: A + verified deterministic issuer-event facts
C: B + Jev event classifications
D: B + Mercury-3 grounded research/extraction
E: B + Jev + Mercury-3 escalations
F: old frozen forecast-v2 as contextual control   (only where comparable)
```

**Selection rule (preregistered):** if Jev improves verification but not
genuine net portfolio results, it is retained only in event intelligence /
evidence checking, never in alpha weights. Mercury cannot emit money-authorised
orders.

## 2. What could be run in W4 — and what is data-blocked

| Arm | Status | Reason (exact) |
|---|---|---|
| A | verified by hash reevaluation | `wave4_w3_control_reevaluation.json` recomputes the frozen W3 feature/label hashes and label counts with `events_ai` present but **never imported** on that path ⇒ Jev OFF leaves the numeric control byte-equivalent (master-prompt acceptance proof) |
| B | **HISTORICAL_EVENT_ABLATION_BLOCKED** | no verified contemporaneous historical corpus of official issuer events exists; the deterministic fact layer cannot be built over the 2015–2023 panel without fabricating contemporaneity |
| C | **HISTORICAL_EVENT_ABLATION_BLOCKED** | requires Arm B's fact layer |
| D | **HISTORICAL_EVENT_ABLATION_BLOCKED** | requires Arm B's fact layer |
| E | **HISTORICAL_EVENT_ABLATION_BLOCKED** | requires Arm B's fact layer |
| F | **NOT_RUN_CONTEXTUAL_ONLY** | forecast-v2 is the production system on a different data plane; the W3 control already carries the comparable contextual comparison (W2 holdout reveal). No new F arm is computed in W4 |

Per master prompt §W4.4: missing historical event capture is **never** pretended
to be a PIT backtest — the blocker is flagged explicitly and prospective event
signals are collected forward (protocol in `wave4_goldset_methodology.md` §4).

## 3. Classification-quality arm (extra, clearly labelled)

`ENGINEERING_CHECK_SYNTHETIC`: paired keyword-baseline (V2 taxonomy, read-only)
vs scripted-Jev on the 24-row synthetic fixture — 19 evaluable rows, paired_n =
19. This measures **machinery**, not real quality; see
`wave4_goldset_metrics.json`.

## 4. Metrics that WILL be computed when B–E unblock

Paired absolute NET NAV, benchmark-relative excess, drawdown, turnover, model
inference costs (token-metered), event-label-quality and limits, from
overlapping daily signals — identical to W3's metric set plus event columns.

## 5. Control-freeze discipline

- The W3 numeric control (feature hash
  `634b3669a3aacde6…`, label hash `0053df3de4d04032…`)
  is frozen; W4 may not touch the files that produce it.
- `quantlab` never imports `events_ai` (AST test); the verifier script itself
  imports only quantlab/warehouse/lab modules.
- Revealed W2 holdout (2024-06-21..2026-09-17) is never reusable for W4 claims.
