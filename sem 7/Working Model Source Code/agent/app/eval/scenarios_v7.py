"""FRESH UNBURNED seventh scenario set (built 2026-10-10, BEFORE any run on it).

Why a new set instead of re-running v6: v6's per-scenario labels were printed to
`data/eval_v6_run.log` and read while diagnosing the m11 hold-bias, so v6 is
contaminated *by us* even though the LLM never saw it. v7 uses the SAME recent
windows as v6 but a DIFFERENT ticker for every pair, so it is unburned in every
sense:

- Same as_of dates as v6 (2026-07-21..2026-08-25) — the most recent window whose
  20-trading-day forward labels already exist (latest as_of + 20 td < build date
  2026-10-10), and at/after the deciders' likely knowledge cutoff.
- Tickers disjoint from v6's list (no (ticker, as_of) pair overlap by
  construction; also asserted vs v1/v5/v3rd/v4).
- 20-day horizon, decisive iff |fwd| >= 4% (shared constants in scenarios.py).
- Labels computed at runtime, NEVER inspected at construction time.

Pre-registration: data/prereg_v7_2026h2.md (written before the run).
"""
from __future__ import annotations

SET_NAME = "v7-2026h2-unburned"

SCENARIOS_V7: list[tuple[str, str]] = [
    # 2026-07-21
    ("ADANIENT.NS", "2026-07-21"),
    ("BAJAJ-AUTO.NS", "2026-07-21"),
    ("BPCL.NS", "2026-07-21"),
    ("BRITANNIA.NS", "2026-07-21"),
    # 2026-07-28
    ("CIPLA.NS", "2026-07-28"),
    ("DRREDDY.NS", "2026-07-28"),
    ("EICHERMOT.NS", "2026-07-28"),
    ("GRASIM.NS", "2026-07-28"),
    # 2026-08-04
    ("HDFCLIFE.NS", "2026-08-04"),
    ("HEROMOTOCO.NS", "2026-08-04"),
    ("HINDALCO.NS", "2026-08-04"),
    ("INDUSINDBK.NS", "2026-08-04"),
    # 2026-08-11
    ("JSWSTEEL.NS", "2026-08-11"),
    ("M&M.NS", "2026-08-11"),
    ("NESTLEIND.NS", "2026-08-11"),
    ("TATACONSUM.NS", "2026-08-11"),
    # 2026-08-18
    ("SBILIFE.NS", "2026-08-18"),  # TATAMOTORS.NS was delisted/404 at this window

    ("TATASTEEL.NS", "2026-08-18"),
    ("TECHM.NS", "2026-08-18"),
    ("UPL.NS", "2026-08-18"),
    # 2026-08-25
    ("DIVISLAB.NS", "2026-08-25"),
    ("APOLLOHOSP.NS", "2026-08-25"),
    ("ADANIPORTS.NS", "2026-08-25"),
    ("BAJAJFINSV.NS", "2026-08-25"),
]
assert len(SCENARIOS_V7) == 24
assert len({t for t, _ in SCENARIOS_V7}) == 24, "each ticker exactly once"

from app.eval.scenarios import SCENARIOS as _V1
from app.eval.scenarios_v5 import SCENARIOS_V5 as _V5
from app.eval.scenarios_v3rd import SCENARIOS_V3RD as _V3
from app.eval.scenarios_v4 import SCENARIOS_V4 as _V4
from app.eval.scenarios_v6 import SCENARIOS_V6 as _V6

assert not (set(SCENARIOS_V7) & set(_V1)), "pair overlap with original-24"
assert not (set(SCENARIOS_V7) & set(_V5)), "pair overlap with v5-2025-disjoint"
assert not (set(SCENARIOS_V7) & set(_V3)), "pair overlap with v3rd-2026-clean"
assert not (set(SCENARIOS_V7) & set(_V4)), "pair overlap with v4-2022-blind"
assert not (set(SCENARIOS_V7) & set(_V6)), "pair overlap with v6-2026h2-unburned"
