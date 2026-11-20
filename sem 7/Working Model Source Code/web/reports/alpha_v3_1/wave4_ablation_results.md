# W4 — Paired financial ablation results (honest)

Generated: 2026-11-14T08:28:47.860313+00:00

| Arm | Status | Evidence / blocker |
|---|---|---|
| A | `UNCHANGED` | wave4_w3_control_reevaluation.json |
| B | `HISTORICAL_EVENT_ABLATION_BLOCKED` | no verified contemporaneous historical issuer-event corpus |
| C | `HISTORICAL_EVENT_ABLATION_BLOCKED` | requires Arm B fact layer |
| D | `HISTORICAL_EVENT_ABLATION_BLOCKED` | requires Arm B fact layer |
| E | `HISTORICAL_EVENT_ABLATION_BLOCKED` | requires Arm B fact layer |
| F | `NOT_RUN_CONTEXTUAL_ONLY` | no comparable new plane; W3 control already carries the contextual comparison |
| classification_engineering_check | `ENGINEERING_CHECK_SYNTHETIC` | wave4_goldset_metrics.json |

**Arm A detail:** verdict from `wave4_w3_control_reevaluation.json` —
`UNCHANGED` (feature/label hashes and label counts recomputed with the
W4 events plane present but off).

**Arms B–E:** `HISTORICAL_EVENT_ABLATION_BLOCKED` — there is no verified
contemporaneous historical issuer-event corpus. No number for these arms exists
anywhere in the W4 artifacts; none is simulated.

**Arm F:** `NOT_RUN_CONTEXTUAL_ONLY` — forecast-v2 comparability was already
carried by the W3 control; no new F run in W4.

**Classification engineering check (not a financial ablation):** paired_n =
19 on the synthetic fixture — baseline
0.4737 vs scripted-model
0.7895 paired accuracy, machinery
verification only (`ENGINEERING_CHECK_SYNTHETIC`).

**Forward path:** collect event signals prospectively per
`wave4_goldset_methodology.md` §4; only then can B–E be run as true PIT
ablations.
