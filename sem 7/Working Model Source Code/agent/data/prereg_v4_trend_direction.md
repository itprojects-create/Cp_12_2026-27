# Pre-registration — regime-driven direction (v4 / "trend" policy)

**Written:** 2026-10-06, BEFORE running any eval on the fresh blind set `v4-2022-blind`.
**Author:** (owner) · **Purpose:** test one pre-specified hypothesis with a single read on
data that has never been evaluated by this system.

## Why this, and why now

Honest baseline analysis (`data/baseline_analysis.json`) found the live LLM pipeline never
beats a trivial constant rule on 11/11 clean runs — its directional selection has negative
skill. Separately, a constant rule conditioned on the market's OWN trend scores above the
frozen accuracy gate on the sets seen so far (always_long ≈0.58–0.62 in up tapes,
always_short ≈0.59 in down tapes). That is the only lever with a plausible positive number.

**Hypothesis H1:** replacing LLM-chosen direction with a deterministic PIT index-trend
direction (and letting the LLM only size/veto) produces decision accuracy ≥ the frozen
0.55 gate on a fresh, unseen scenario set.

**Explicit caveat, stated before seeing data:** if H1 holds it is most likely *market beta
/ regime alignment*, not alpha. That is an acceptable, disclosable result for this project;
it is NOT evidence the LLM picks stocks.

## The rule (frozen now — do not change after the run)

Evaluated in code, after all LLM reasoning, in `run_pm` when `DIRECTION_POLICY=trend`:

1. `trend = market_trend_at(as_of)` on `^NSEI` — UP if close>MA50 and MA20>MA50; DOWN if
   close<MA50 and MA20<MA50; else RANGE; UNKNOWN on missing data (PIT-safe, ≥60 bars).
2. Direction override:
   - trend UP   → long  (action `buy`)
   - trend DOWN → short (action `sell`)
   - trend RANGE / UNKNOWN → no trade (`hold`, size 0)  ← the no-edge branch
3. Preserved vetoes (unchanged): thesis `flat` → hold; challenge `BROKEN` → hold;
   STRESSED + MOMENTUM (M3 VIX gate) → hold.
4. Size: `min(0.10, proposal.size_pct if >0 else 0.03)` — deterministic, not LLM-sized.

No prompt, gate, schema, or contract changes. `PROMPT_VERSION` and the direction policy are
both in the session config hash, so trend vs llm sessions never collide.

## Success criteria (frozen 2026-09-18 gates, unchanged)

PASS requires ALL of: `n_decisive ≥ 8` · `accuracy ≥ 0.55` · `no_edge_hold ≥ 0.40` ·
`trade_rate ∈ [0.20,0.90]` · calibration direction positive. Plus the honest anchor added
2026-10-06: **must beat the best constant rule** (`beats_best_constant = True`) for the
result to count as skill rather than drift.

## Decision rule for the outcome

- **PASS and beats best constant** → the system has a defensible (likely beta) edge; report
  it with the beta caveat. Move to risk/portfolio integration.
- **PASS but does not beat constant** → market drift, not skill; report as such.
- **FAIL** → no honest positive result exists here; stop iterating on direction and reframe
  the objective (no-edge detection / risk control). Do NOT tune prompts to chase the number.

One read. No re-runs to chase the number. Whatever comes out is recorded as-is.
