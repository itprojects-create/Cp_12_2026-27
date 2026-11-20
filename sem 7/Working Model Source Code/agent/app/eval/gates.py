"""PRE-REGISTERED EVAL GATES — FROZEN 2026-09-18, before the first live eval run.

These thresholds were fixed a priori from the quant-plus gate discipline, NOT tuned
to results. Do not move them after seeing the report. Edit only with a new date +
written reason, and re-run the full harness.

Rationale for modest bars: n=24 scenarios (~8-14 decisive) has wide binomial error
bars; gates test for (a) better-than-chance direction, (b) honest no-edge behavior,
(c) sane calibration, (d) no degenerate always-trade/always-hold policy.
"""
from __future__ import annotations

FROZEN_DATE = "2026-09-18"
MIN_DECISIVE = 8          # fewer decisive scenarios -> verdict INCONCLUSIVE, not PASS
ACCURACY_MIN = 0.55       # P(correct | decisive label) — above coin flip
NO_EDGE_HOLD_MIN = 0.40   # P(hold | flat label) — must sometimes say "no edge"
TRADE_RATE_LO = 0.20      # guards always-hold degeneracy
TRADE_RATE_HI = 0.90      # guards always-trade degeneracy
# Calibration is directional (informational PASS/FAIL): mean conviction(correct) >
# mean conviction(wrong). No numeric bar — direction only, given small n.
