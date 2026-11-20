"""CLEAN third scenario set (built 2026-09-20, BEFORE any eval run on it).

Construction discipline (same as v5 set, new window):
- 2026-01..2026-07 windows: no date overlap with original-24 (2023-07..2024-12)
  or v5-2025-disjoint (2025-01..2025-12); each ticker used exactly once.
- NIFTY large/mid-caps, all verified present on Yahoo at build time.
- Regime mix from trailing India-VIX percentiles at selection (market data only):
  CALM=4, ELEVATED=12, STRESSED=8 — the Mar-May 2026 stress cluster is real tape,
  kept deliberately rather than smoothed away.
- 20-day horizon, decisive iff |fwd| >= 4% (shared constants in scenarios.py).
- Labels computed at runtime, unseen at construction time. No pipeline
  predictions were checked on any candidate before finalizing.
- Same frozen gate definitions/values (app/eval/gates.py, unchanged).
"""
from __future__ import annotations

SET_NAME = "v3rd-2026-clean"

SCENARIOS_V3RD: list[tuple[str, str]] = [
    ("RELIANCE.NS", "2026-01-06"),
    ("INFY.NS", "2026-01-13"),
    ("TCS.NS", "2026-01-20"),
    ("HDFCBANK.NS", "2026-01-27"),
    ("ICICIBANK.NS", "2026-02-03"),
    ("SBIN.NS", "2026-02-10"),
    ("AXISBANK.NS", "2026-02-17"),
    ("KOTAKBANK.NS", "2026-02-24"),
    ("MARUTI.NS", "2026-03-03"),
    ("TITAN.NS", "2026-03-10"),
    ("SUNPHARMA.NS", "2026-03-17"),
    ("ULTRACEMCO.NS", "2026-03-24"),
    ("NTPC.NS", "2026-03-31"),
    ("POWERGRID.NS", "2026-04-07"),
    ("ONGC.NS", "2026-04-14"),
    ("CIPLA.NS", "2026-04-21"),
    ("DRREDDY.NS", "2026-05-05"),
    ("JSWSTEEL.NS", "2026-05-12"),
    ("HINDALCO.NS", "2026-05-26"),
    ("GRASIM.NS", "2026-06-02"),
    ("BAJAJ-AUTO.NS", "2026-06-16"),
    ("COALINDIA.NS", "2026-06-30"),
    ("BHARTIARTL.NS", "2026-07-07"),
    ("HCLTECH.NS", "2026-07-14"),
]
assert len(SCENARIOS_V3RD) == 24
assert len({t for t, _ in SCENARIOS_V3RD}) == 24, "each ticker exactly once"

from app.eval.scenarios import SCENARIOS as _V1
from app.eval.scenarios_v5 import SCENARIOS_V5 as _V5

assert not (set(SCENARIOS_V3RD) & set(_V1)), "pair overlap with original-24"
assert not (set(SCENARIOS_V3RD) & set(_V5)), "pair overlap with new-24"
