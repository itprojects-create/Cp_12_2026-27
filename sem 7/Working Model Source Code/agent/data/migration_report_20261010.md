# QUANTPLUS ARCHITECTURE MIGRATION REPORT — prediction system → research OS

**Date:** 2026-10-10 · **HEAD after migration:** (see git log) · **Suite:** 269/269 green (baseline 212 pre-migration)
**Constitution:** `app/governance/constitution.py` v1 + `docs/QUANTPLUS_CONSTITUTION.md`
**Spend:** zero new LLM inference for the migration itself (all new paths deterministic; paid evals untouched)

## A. Architecture summary (old vs new)

OLD: analysts → debate → manager → Devil → trader → risk → PM produced a
`FinalDecision{buy/sell/hold, size}` whose direction was LLM-originated
(`DIRECTION_POLICY=llm`) and served as the system's trading voice. Money path
separation existed only by convention (paper script + boundary fn, no live caller).

NEW: the session pipeline is **RESEARCH_ONLY by type** (`FinalDecision.authority`
+ three invariant literals, `assert_research_only` fails closed). Capital flows only
through deterministic code (frozen v4 core → veto → risk caps). LLMs operate a
quant R&D org: 7 roles → hypotheses → DSL → foundry/falsification → expanded eval →
champion gate → shadow → forward clock → promotion. Failure is a first-class asset
(corpse registry, lineage, reopening only on new evidence).

## B. File change list

| Path | Purpose | Major changes |
|---|---|---|
| `app/governance/__init__.py`, `constitution.py` | Machine-readable R1–R15 | rules/gatesets/dataset registry/status labels/research-output contract/`describe()` guard/`assert_research_only` |
| `docs/QUANTPLUS_CONSTITUTION.md` | Human-readable constitution | 15 rules, safe defaults, evidence ladder |
| `app/schemas.py` | Type-level boundary | `FinalDecision.authority=RESEARCH_ONLY` + 3 invariant flags (additive) |
| `app/config.py`, `.env.example` | §55 flags | 9 authority flags, all safe defaults |
| `app/core/overlay.py` | Enforced A/B/C switch | `apply_llm_overlay()` (OFF=control identity; ON needs experimental tag) |
| `app/research/__init__.py`, `schema.py`, `fingerprints.py` | §§5,7 | hypothesis/experiment/falsification schemas (capital-directive rejection), stable fps |
| `app/foundry/dsl.py` | §6 Strategy DSL | 17 allowed ops, 9 rejected classes, WEIGHT≤1 by construction, compile+fingerprint, foundry bridge |
| `app/research_memory/*` (6 files) | §8 research memory | hypotheses/experiments/corpses/lineage tables, dedup, DEAD_MATCH, reopen-on-evidence, retrieval, evidence records, manifests helper |
| `app/research/roles.py`, `director.py`, `falsifier.py`, `specialists.py` | §4 role migration | 7 roles, output-contract validation, deterministic prioritize/dedup, falsifier menu+family plans, corpse-aware briefs |
| `app/eval/stats.py`, `incremental_alpha.py`, `concentration.py`, `regimes.py`, `stability.py`, `loo.py`, `placebo.py`, `benchmarks.py`, `data_quality.py`, `report.py` | §§11–22,36 | full expansion layer + failure-first report |
| `app/evo/promotion.py`, `champion.py` | §§17–18 | GATESET_V1 (documented kill-favoring bars), pool/champion-history, genesis, promote/retire |
| `app/research/orchestrator.py` | §§9,27 | OBSERVE→QUEUE cycle, no LLM inside (injected propose_fn), manifests, cost ledger |
| `app/api/research.py`, `app/main.py` | §54 | 7 additive research endpoints, router registered |
| `app/events/*` (6 files) | §24 | ingest/normalize/classify/schemas/blackout; Extraction model (no identity); LLM gate rejects orders |
| `scripts/ablate_overlay.py`, `scripts/reproduce_experiment.py` | §§23,28 | A/B/C ablation (frozen rules); experiment reproduction |
| `contract/*`, `frontend-client/client.ts` | compat | regen additive (18 schemas; +7 research paths) |
| `data/overlay_ablation_20261010.json` | §23 verdict | C vs A on 360 cached decisions → OFF |
| tests (8 new files) | §44 | governance, schema/dsl, memory, roles, eval-expansion, champion, orchestrator, announcements, ablation |

## C. Capital authority audit

Components capable of affecting capital: `run_core_v4` (direction/size) →
`veto_fraction`/`apply_veto` (shrink-only) → `apply_llm_overlay` (OFF=identity) →
position sizing in paper ledger → risk caps (gross/sector/vol) → kill-switch.
**No LLM component has capital authority:** all 14 `call_json` sites terminate in
RESEARCH_ONLY outputs; `broker_angel` has no order function (tested); confidence
never maps to size (tested across convictions); overlay defaults OFF (tested).

## D. Research workflow (one lifecycle, executed live in tests)

Microstructure brief ("delivery predicts direction") → memory returns MATCHED PRIOR
CORPSE (delivery-as-direction, failed 4 ways, reuse: exhaustion context only) →
hypothesis submitted → exact-duplicate second submit → DUPLICATE → experiment recorded →
FAILED_BACKTEST outcome → corpse buried with evidence-required → resubmission →
DEAD_MATCH → reopened only with new PIT-regime evidence. (Covered end-to-end in
`tests/test_research_memory.py` + orchestrator cycle test.)

## E. Tests

Before: 212 green. After: 269 green (57 new: 12 governance, 9 schema/dsl, 5 memory,
6 roles, 10 eval-expansion, 2 champion, 4 orchestrator/API, 6 announcements, 3 ablation).
Zero regressions; one contract-drift caught by the snapshot test itself and resolved
via regen. Three test-side fixture errors + one lenient gate + one design flaw
(Extraction identity) found and fixed during the run — all recorded in-test, none hidden.

## F. Migration risks (remaining weaknesses)

1. v6/v7 direction evals partial (14/24, 10/24) — research read incomplete; finishing
   costs ~1M tokens and changes no decision (money path independent).
2. Broad DSR recompute + full Devil-off ablation bill still queued (funded window).
3. Announcement live fetch is best-effort (exchange endpoints drift); deterministic
   value today comes from committed JSONL feeds, which do not exist yet.
4. `Experimental` LLM-overlay path exists (tagged) — a future integrator could enable
   it; the flag default + ablation OFF verdict + required tag are the guardrails.
5. Per-rebalance time-varying PIT membership still a core-loop change (deferred).
6. Research-agent calibration (§41) needs survived/failed outcomes that only forward
   time produces — metric defined, data pending.

## G. Deprecated (kept for backward compatibility)

`DIRECTION_POLICY=trend/llm` as capital authority (research-path selector only now);
trader/risk/PM LLM sizing (code-owned since F2 fix; retained for archival evals);
devil-off ablation harness; single-name direction eval sets (all burned; falsification-only).

## H. Next recommended experiment (no historical optimization)

Announcement-feed blackout pipeline on FORWARD data: commit 2–4 weeks of NSE JSONL
feeds → normalize/classify → propose `blackout_window` via foundry → embargoed
validation on forward rows only → shadow. It exercises every new layer (roles, DSL,
events, memory, gates, forward clock) without touching the burned window.
