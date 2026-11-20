"""FRESH UNBURNED sixth scenario set (built 2026-10-10, BEFORE any run on it).

Construction discipline (same as v5/v3rd/v4 sets, newest window):
- 2026-07-21..2026-08-25 windows: zero date overlap with original-24
  (2023-07..2024-12), v5-2025-disjoint (2025), v4-2022-blind (2022-08..2023-01),
  or v3rd-2026-clean (2026-01..2026-07-14). Each ticker used once.
- Chosen as the most recent window whose 20-trading-day forward labels already
  exist (latest as_of + 20 trading days < build date 2026-10-10). Recent dates
  also sit at/after the decider/analyst models' likely knowledge cutoff, so the
  read is not just unread-by-us but closer to un-leaked-by-training.
- 20-day horizon, decisive iff |fwd| >= 4% (shared constants in scenarios.py).
- Labels computed at runtime, NEVER inspected at construction time.
- Same frozen gates (app/eval/gates.py, unchanged).

Pre-registration note: data/prereg_v6_2026h2.md (written before the run).
"""
from __future__ import annotations

SET_NAME = "v6-2026h2-unburned"

SCENARIOS_V6: list[tuple[str, str]] = [
    ("RELIANCE.NS", "2026-07-21"),
    ("HDFCBANK.NS", "2026-07-21"),
    ("ICICIBANK.NS", "2026-07-21"),
    ("INFY.NS", "2026-07-21"),
    ("TCS.NS", "2026-07-28"),
    ("ITC.NS", "2026-07-28"),
    ("LT.NS", "2026-07-28"),
    ("SBIN.NS", "2026-07-28"),
    ("BHARTIARTL.NS", "2026-08-04"),
    ("KOTAKBANK.NS", "2026-08-04"),
    ("HINDUNILVR.NS", "2026-08-04"),
    ("AXISBANK.NS", "2026-08-04"),
    ("BAJFINANCE.NS", "2026-08-11"),
    ("MARUTI.NS", "2026-08-11"),
    ("TITAN.NS", "2026-08-11"),
    ("SUNPHARMA.NS", "2026-08-11"),
    ("WIPRO.NS", "2026-08-18"),
    ("NTPC.NS", "2026-08-18"),
    ("POWERGRID.NS", "2026-08-18"),
    ("ULTRACEMCO.NS", "2026-08-18"),
    ("HCLTECH.NS", "2026-08-25"),
    ("ONGC.NS", "2026-08-25"),
    ("COALINDIA.NS", "2026-08-25"),
    ("ASIANPAINT.NS", "2026-08-25"),
]
assert len(SCENARIOS_V6) == 24
assert len({t for t, _ in SCENARIOS_V6}) == 24, "each ticker exactly once"

from app.eval.scenarios import SCENARIOS as _V1
from app.eval.scenarios_v5 import SCENARIOS_V5 as _V5
from app.eval.scenarios_v3rd import SCENARIOS_V3RD as _V3
from app.eval.scenarios_v4 import SCENARIOS_V4 as _V4

assert not (set(SCENARIOS_V6) & set(_V1)), "pair overlap with original-24"
assert not (set(SCENARIOS_V6) & set(_V5)), "pair overlap with v5-2025-disjoint"
assert not (set(SCENARIOS_V6) & set(_V3)), "pair overlap with v3rd-2026-clean"
assert not (set(SCENARIOS_V6) & set(_V4)), "pair overlap with v4-2022-blind"
