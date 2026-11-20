"""FRESH BLIND fourth scenario set (built 2026-10-06, BEFORE any run on it).

Construction discipline (same as v5/v3rd sets, new window):
- 2022-08..2023-01 windows: zero date overlap with original-24 (2023-07..2024-12),
  v5-2025-disjoint (2025), or v3rd-2026-clean (2026-01..07). Each ticker used once.
- 2022 was a choppy/range-bound-to-bear tape for Indian large caps — deliberately a
  DIFFERENT regime from the bull (2025) and stress (2026) sets, so a regime-alignment
  rule is tested out-of-regime.
- 20-day horizon, decisive iff |fwd| >= 4% (shared constants in scenarios.py).
- Labels computed at runtime, NEVER inspected at construction time.
- Same frozen gates (app/eval/gates.py, unchanged) + the new honest constant-rule anchor.

Pre-registered hypothesis + rule: see data/prereg_v4_trend_direction.md.
"""
from __future__ import annotations

SET_NAME = "v4-2022-blind"

SCENARIOS_V4: list[tuple[str, str]] = [
    ("RELIANCE.NS", "2022-08-02"),
    ("TCS.NS", "2022-08-09"),
    ("HDFCBANK.NS", "2022-08-16"),
    ("INFY.NS", "2022-08-23"),
    ("ICICIBANK.NS", "2022-08-30"),
    ("SBIN.NS", "2022-09-06"),
    ("BHARTIARTL.NS", "2022-09-13"),
    ("ITC.NS", "2022-09-20"),
    ("LT.NS", "2022-09-27"),
    ("KOTAKBANK.NS", "2022-10-04"),
    ("AXISBANK.NS", "2022-10-11"),
    ("HINDUNILVR.NS", "2022-10-18"),
    ("BAJFINANCE.NS", "2022-10-25"),
    ("MARUTI.NS", "2022-11-01"),
    ("TITAN.NS", "2022-11-08"),
    ("ASIANPAINT.NS", "2022-11-15"),
    ("SUNPHARMA.NS", "2022-11-22"),
    ("WIPRO.NS", "2022-11-29"),
    ("NTPC.NS", "2022-12-06"),
    ("POWERGRID.NS", "2022-12-13"),
    ("ULTRACEMCO.NS", "2022-12-20"),
    ("HCLTECH.NS", "2022-12-27"),
    ("ONGC.NS", "2023-01-03"),
    ("COALINDIA.NS", "2023-01-10"),
]
assert len(SCENARIOS_V4) == 24
assert len({t for t, _ in SCENARIOS_V4}) == 24, "each ticker exactly once"

from app.eval.scenarios import SCENARIOS as _V1
from app.eval.scenarios_v5 import SCENARIOS_V5 as _V5
from app.eval.scenarios_v3rd import SCENARIOS_V3RD as _V3

assert not (set(SCENARIOS_V4) & set(_V1)), "pair overlap with original-24"
assert not (set(SCENARIOS_V4) & set(_V5)), "pair overlap with new-24"
assert not (set(SCENARIOS_V4) & set(_V3)), "pair overlap with v3rd-24"
