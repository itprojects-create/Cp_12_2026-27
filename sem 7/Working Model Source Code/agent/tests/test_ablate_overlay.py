"""Overlay ablation tests (Phase 9). Synthetic only — verdict logic, no history."""
from __future__ import annotations

import sys

sys.path.insert(0, "scripts")
from ablate_overlay import COST_LOWER_RS, run_books, scenario_pnl, verdict


def test_scenario_pnl_costs():
    assert scenario_pnl(0.0, 0.10) == 0.0
    assert scenario_pnl(0.05, 0.10) < 0.05 * 0.10  # cost deducted
    assert scenario_pnl(0.05, -0.10) < 0


def test_overlay_mechanics_on_cached_shape():
    # Opposite LLM view -> veto to 0 (never a flip, even when the veto
    # forfeits a winning core position — the documented cost of veto-only).
    # Agreeing view -> resize down. Hold -> core stands untouched.
    scenarios = [
        {"as_of": "2026-01-01", "instrument": "A.NS", "action": "sell",
         "size": 0.025, "fwd_ret": 0.10},
        {"as_of": "2026-01-02", "instrument": "B.NS", "action": "buy",
         "size": 0.025, "fwd_ret": -0.10},
        {"as_of": "2026-01-03", "instrument": "C.NS", "action": "hold",
         "size": 0.0, "fwd_ret": 0.10},
    ]
    books = run_books(scenarios, capital=100000.0)
    assert books["n"] == 3
    assert books["n_veto"] == 1 and books["n_resize"] == 1 and books["n_pass"] == 1
    # A books the rally on all three; C banks only the hold pass + resized loss.
    assert books["A_profit"] > 0
    assert books["C_profit"] < books["A_profit"]  # veto forfeits upside here


def test_verdict_rules_frozen():
    off = verdict({"C_minus_A": -100.0, "n": 10})
    assert off["verdict"] == "OFF" and off["config_change"].startswith("none")
    thin = verdict({"C_minus_A": 10 * COST_LOWER_RS - 1, "n": 10})
    assert thin["verdict"] == "OFF" and "inference" in thin["why"]
    cond = verdict({"C_minus_A": 10 * COST_LOWER_RS + 1, "n": 10})
    assert cond["verdict"] == "CONDITIONAL-ON"
    assert cond["cost_lower_rs"] == 10 * COST_LOWER_RS
