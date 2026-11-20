"""Held-out eval scenarios: 24 (instrument, as_of) pairs spanning 2023-07..2024-12 regimes.

Labels are computed ONLY from post-as_of forward returns (ground truth for scoring);
agents never see post-as_of data (PIT provider enforces available_at <= as_of).
Horizon 20 trading days; decisive if |fwd| >= 4%, else flat (no-edge expected).
"""
from __future__ import annotations

HORIZON_DAYS = 20
DECISIVE_RET = 0.04

SCENARIOS: list[tuple[str, str]] = [
    ("RELIANCE.NS", "2023-07-10"),
    ("INFY.NS", "2023-08-08"),
    ("HDFCBANK.NS", "2023-09-12"),
    ("TCS.NS", "2023-10-25"),
    ("ICICIBANK.NS", "2023-11-15"),
    ("SBIN.NS", "2023-12-05"),
    # TATAMOTORS.NS removed 2026-09-18: delisted after 2025 demerger (Yahoo 404). Replaced below, same date.
    ("EICHERMOT.NS", "2024-01-16"),
    ("TITAN.NS", "2024-02-12"),
    ("SUNPHARMA.NS", "2024-03-14"),
    ("LT.NS", "2024-04-10"),
    ("AXISBANK.NS", "2024-05-08"),
    ("KOTAKBANK.NS", "2024-06-05"),
    ("MARUTI.NS", "2024-06-20"),
    ("ULTRACEMCO.NS", "2024-07-11"),
    ("NTPC.NS", "2024-08-06"),
    ("POWERGRID.NS", "2024-08-22"),
    ("ONGC.NS", "2024-09-10"),
    ("COALINDIA.NS", "2024-09-26"),
    ("BHARTIARTL.NS", "2024-10-15"),
    ("HCLTECH.NS", "2024-10-29"),
    ("BAJFINANCE.NS", "2024-11-14"),
    ("ASIANPAINT.NS", "2024-11-28"),
    ("ADANIENT.NS", "2024-12-10"),
    ("WIPRO.NS", "2024-12-26"),
]
assert len(SCENARIOS) >= 24
