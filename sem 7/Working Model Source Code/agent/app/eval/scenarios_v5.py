"""DISJOINT v5 scenario set (built BEFORE any v5 eval run — 2026-09-19).

Disjointness rules (per v5 task):
- All windows in 2025: non-overlapping with the original 2023-07→2024-12 set.
- NONE of the 8 diagnosis-contaminated tickers appear (KOTAKBANK, BAJFINANCE,
  SBIN, EICHERMOT, BHARTIARTL, COALINDIA, HDFCBANK, LT).
- Same construction: NIFTY large-caps, mixed regimes, 20-day horizon,
  decisive iff |fwd| >= 4% (see scenarios.py constants, shared).
- Same frozen gate definitions/values (app/eval/gates.py, unchanged).
- Original 24 kept permanently in scenarios.py; labels computed at runtime,
  unseen at construction time.
"""
from __future__ import annotations

SET_NAME = "v5-2025-disjoint"

SCENARIOS_V5: list[tuple[str, str]] = [
    ("TCS.NS", "2025-01-14"),
    ("NTPC.NS", "2025-01-28"),
    ("SUNPHARMA.NS", "2025-02-11"),
    ("POWERGRID.NS", "2025-02-25"),
    ("INFY.NS", "2025-03-11"),
    ("MARUTI.NS", "2025-03-25"),
    ("ICICIBANK.NS", "2025-04-08"),
    ("TITAN.NS", "2025-04-22"),
    ("ULTRACEMCO.NS", "2025-05-13"),
    ("ONGC.NS", "2025-05-27"),
    ("AXISBANK.NS", "2025-06-10"),
    ("HCLTECH.NS", "2025-06-24"),
    ("WIPRO.NS", "2025-07-08"),
    ("ASIANPAINT.NS", "2025-07-22"),
    ("TCS.NS", "2025-08-12"),
    ("NTPC.NS", "2025-08-26"),
    ("SUNPHARMA.NS", "2025-09-09"),
    ("INFY.NS", "2025-09-23"),
    ("RELIANCE.NS", "2025-10-07"),
    ("TITAN.NS", "2025-10-21"),
    ("MARUTI.NS", "2025-11-11"),
    ("POWERGRID.NS", "2025-11-25"),
    ("ULTRACEMCO.NS", "2025-12-09"),
    ("ONGC.NS", "2025-12-16"),
]
assert len(SCENARIOS_V5) == 24
_CONTAMINATED = {"KOTAKBANK.NS", "BAJFINANCE.NS", "SBIN.NS", "EICHERMOT.NS",
                 "BHARTIARTL.NS", "COALINDIA.NS", "HDFCBANK.NS", "LT.NS"}
assert not (_CONTAMINATED & {t for t, _ in SCENARIOS_V5}), "contaminated ticker in v5 set"
