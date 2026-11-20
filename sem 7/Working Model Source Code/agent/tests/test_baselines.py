"""Baseline + significance tests: pure functions, zero tokens, no network."""
from __future__ import annotations

from app.eval.baselines import (
    DIRECTION, POLICIES, binomial_pvalue, bootstrap_ci, compare, evaluate, load_rows,
)


def _row(label, action, size=0.03, fwd=0.0):
    return {"instrument": "X.NS", "as_of": "2024-01-01", "label": label,
            "action": action, "size": size, "fwd_ret": fwd}


def test_load_rows_skips_malformed():
    report = {"results": [
        _row("long", "buy"),
        {"instrument": "Y.NS", "action": "buy"},            # missing label/fwd
        {"action": "buy", "label": "long"},                  # missing fwd_ret -> skipped
        _row("flat", "hold"),
    ]}
    rows = load_rows(report)
    assert len(rows) == 2 and all("fwd_ret" in r for r in rows)


def test_evaluate_metrics_and_pnl():
    rows = [_row("long", "buy", size=0.03, fwd=0.06),
            _row("short", "sell", size=0.03, fwd=-0.10),
            _row("long", "sell", size=0.03, fwd=0.05),   # wrong
            _row("flat", "hold", size=0.0, fwd=0.01)]
    m = evaluate(rows, POLICIES["agent"])
    assert m["n"] == 4 and m["n_decisive"] == 3 and m["n_correct"] == 2
    assert abs(m["accuracy"] - 2 / 3) < 1e-9
    assert m["no_edge_hold_rate"] == 1.0
    assert m["trade_rate"] == 0.75
    # buy +6% at 3% size, minus round-trip cost on the traded notional
    from app.data.base import ROUNDTRIP_COST
    exp = 0.03 * 0.06 - 0.03 * ROUNDTRIP_COST + 0.03 * 0.10 - 0.03 * ROUNDTRIP_COST - 0.03 * 0.05 - 0.03 * ROUNDTRIP_COST
    assert abs(m["total_pnl"] - exp) < 1e-9


def test_constant_policies():
    rows = [_row("long", "buy", fwd=0.1), _row("short", "sell", fwd=-0.1), _row("flat", "hold", fwd=0.0)]
    assert evaluate(rows, POLICIES["always_long"])["accuracy"] == 0.5
    assert evaluate(rows, POLICIES["always_short"])["accuracy"] == 0.5
    assert evaluate(rows, POLICIES["always_hold"])["trade_rate"] == 0.0
    assert evaluate(rows, POLICIES["always_hold"])["no_edge_hold_rate"] == 1.0


def test_agent_inverse_flips_trades_only():
    rows = [_row("long", "sell"), _row("short", "buy"), _row("flat", "hold")]
    inv = evaluate(rows, POLICIES["agent_inverse"])
    assert inv["n_correct"] == 2 and inv["no_edge_hold_rate"] == 1.0


def test_binomial_pvalue_known_values():
    # all-correct at n=10 is a strong one-in-1024 tail (two-sided ~ 2/1024)
    assert binomial_pvalue(10, 10) < 0.01
    assert abs(binomial_pvalue(5, 10) - 1.0) < 1e-9          # dead-on chance
    assert binomial_pvalue(0, 10) < 0.01
    assert binomial_pvalue(3, 17) < 0.05                     # the m8 v3rd run
    assert binomial_pvalue(0, 0) == 1.0


def test_bootstrap_ci_bounds_and_determinism():
    lo, hi = bootstrap_ci([1, 0, 1, 1, 0, 1, 1, 0])
    assert 0.0 <= lo <= hi <= 1.0
    assert bootstrap_ci([1, 1, 1, 1]) == (1.0, 1.0)
    assert bootstrap_ci([1, 0, 1, 0]) == bootstrap_ci([1, 0, 1, 0])  # seeded
    assert bootstrap_ci([]) == (0.0, 1.0)


def test_compare_flags_anti_predictive_agent():
    # agent goes the wrong way on every decisive call; inverse must score 1.0
    report = {"results": [_row("long", "sell", fwd=0.1), _row("short", "buy", fwd=-0.1),
                          _row("short", "buy", fwd=-0.2), _row("long", "sell", fwd=0.15),
                          _row("long", "sell", fwd=0.2), _row("short", "buy", fwd=-0.05),
                          _row("short", "buy", fwd=-0.09), _row("long", "sell", fwd=0.3)]}
    cmp = compare(report)
    assert cmp["scores"]["agent"]["accuracy"] == 0.0
    assert cmp["scores"]["agent_inverse"]["accuracy"] == 1.0
    assert cmp["agent_binomial_p_vs_0_5"] < 0.02
    assert cmp["beats_chance"] is True           # CI upper bound is below 0.5
    assert cmp["beats_best_constant"] is False


def test_compare_neutral_agent_is_inconclusive():
    report = {"results": [_row("long", "buy"), _row("short", "sell"),
                          _row("long", "sell"), _row("short", "buy")]}
    cmp = compare(report)
    assert cmp["scores"]["agent"]["accuracy"] == 0.5
    assert cmp["beats_chance"] is False


def test_direction_map_complete():
    assert set(DIRECTION) == {"buy", "sell", "hold"}
    assert set(POLICIES) == {"agent", "always_hold", "always_long", "always_short", "agent_inverse"}
