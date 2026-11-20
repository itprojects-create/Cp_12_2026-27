# Prereg: Day-4 hypothesis foundry + positioning veto (NEWW_PLAN)

**Written:** before any Day-4 code or validation run. Deterministic, zero tokens
in the validation loop (LLM prose, if any, is log-only and never a gate input).

## 1. Foundry: allowlisted proposal types ONLY

A proposal is `{kind, params}` where kind ∈ allowlist. Anything else is
rejected at parse time (never evaluated, logged as rejected):

| kind | params (ranges) | Effect if promoted |
|---|---|---|
| `veto_band_edge` | band_lo/hi ∈ {0.1..0.9 step 0.05}, veto ∈ {0.25,0.5,0.75,1.0} on (regime, breadth-bucket) cell | Adds ONE cell to an additive veto table (OR with frozen table — only ever vetoes more, never less) |
| `topK_value` | K ∈ {30, 50, 70} | Genome-range admission only (evo consumes, never live-direct) |
| `blackout_window` | pre ∈ {0..5}, post ∈ {0..3} days | Earnings-blackout width (veto-only timing) |

Forbidden: direction flips, size increases, new indicators, threshold tightening
that *reduces* vetoing (deregulation is not a hypothesis here).

## 2. Embargoed validation + PBO-lite promotion rule

- Split: candidate trains on bars [:60%], embargo gap 20 bars, tests on (60%+gap:].
  The gap defeats leakage through veto-score autocorrelation. Train/test split
  points are fixed constants, not tuned.
- Metric: whipsaw-rate reduction on test slice vs frozen-table baseline at
  matched exposure (±2pp tolerance — vetoes that just go flat everywhere fail).
- PBO-lite: 8 contiguous block-splits of the test slice; candidate must beat
  baseline on ≥6/8 blocks (no single-regime heroics).
- Promotion (ALL required): test whipsaw-rate ↓ ≥2pp vs baseline AND ≥6/8
  blocks AND exposure within ±5pp AND thresholds unchanged since proposal.
  Promotions append to `foundry_log` + (if genome-shaped) evo candidate queue.
  Failures are recorded identically — the log must contain corpses.
- **Amendment 1 (same day, pre-first-run, found in test design):** the original
  ↓≥3pp / ±2pp gate is mathematically infeasible for skip-only vetoes
  (whipsaw drop ≤ newly-vetoed fraction, so 3pp drop needed ≥3pp drift but only
  2pp allowed). Relaxed to ↓≥2pp / ±5pp. Blocks use the same ±5pp.

## 3. Positioning veto (one, preregistered)

`positioning_veto(delivery_z, fii_net_5d, pcr, pcr_hist_pct)` → fraction in [0,1]:

- delivery_z ≤ −2.0 (distribution extreme, PIT 1-session lag) → 0.5
- fii_net_5d < 0 AND pcr_hist_pct ≥ 90 (foreigners selling into complacent put
  writing) → 0.5
- both → 1.0. Anything unavailable → that leg abstains (never imputes, never
  defaults to danger or safety — missing leg contributes 0.0 with a flag).
- Combined with frozen veto by max() (veto-only preserved).

Inputs: delivery from `DeliveryStore` (archive, PIT-clean); FII/PCR from new
`positioning.py` provider (NSE fetch attempt → UNAVAILABLE on any failure;
synthetic fixtures in tests; no Yahoo — it doesn't carry them).

## Gate

Day-4 exit = mechanism proof: schema rejects 3 forbidden kinds; a deliberately
bad proposal (veto-everything) fails promotion ON RECORD (exposure collapse);
embargo gap test proves train/test separation; positioning veto bounds +
unavailable-leg behavior on synthetics. No live veto changes; no evo admission
until Day-6 clock (promotion log is a queue, not a deployment).
