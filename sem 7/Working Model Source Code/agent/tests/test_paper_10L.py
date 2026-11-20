"""Paper-ledger tests (zero tokens): reconciliation, integer shares, cash sanity."""


def _toy():
    idx = [100 + i * 0.3 for i in range(200)]
    names = {f"N{i}.NS": [50 + i + j * 0.2 for j in range(200)] for i in range(6)}
    return idx, names


def test_reconciliation_matches_frozen_v4():
    from app.core.trend_core_v4 import run_core_v4
    import sys
    sys.path.insert(0, "scripts")
    from paper_trade_10L import replay_ledger
    idx, names = _toy()
    ref = run_core_v4(idx, names)
    led = replay_ledger(idx, names, None, {}, {}, 1000000.0)
    worst = max(abs(a - b) for a, b in zip(ref.eq_curve, led["shadow_curve"]))
    assert worst < 1e-9


def test_decision_log_complete_and_consistent():
    import sys
    sys.path.insert(0, "scripts")
    from paper_trade_10L import replay_ledger, REBALANCE_DAYS
    idx, names = _toy()
    dates = [f"2024-01-{(i % 28) + 1:02d}" for i in range(200)]
    rec: list = []
    led = replay_ledger(idx, names, None, {}, {}, 1000000.0, dates=dates, record=rec)
    assert len(rec) == 200 // REBALANCE_DAYS  # one record per rebalance
    for d in rec:
        assert {"date", "trend", "regime", "breadth", "n_qualified", "n_selected",
                "n_held", "stressed_blocked", "vetoes", "veto_blocked",
                "gross", "rebalance_cost", "trades"} <= set(d)
        assert 0.0 <= d["gross"] <= 1.0 + 1e-9
        for t in d["trades"]:
            assert t["side"] in ("buy", "sell") and t["shares_after"] >= 0
            assert t["traded_value"] >= 0 and t["cost"] >= 0
    # cost identity: per-rebalance costs sum to ledger total
    assert abs(sum(d["rebalance_cost"] for d in rec) - led["cost_rupees"]) < 1.0
    # without record list, numbers are identical (read-only instrumentation)
    led2 = replay_ledger(idx, names, None, {}, {}, 1000000.0)
    assert abs(led2["ledger_curve"][-1] - led["ledger_curve"][-1]) < 1e-9


def test_integer_shares_and_cash():
    import sys
    sys.path.insert(0, "scripts")
    from paper_trade_10L import replay_ledger
    idx, names = _toy()
    led = replay_ledger(idx, names, None, {}, {}, 1000000.0)
    assert all(isinstance(s, int) and s >= 0 for s in led["shares"].values())
    assert led["cash"] >= -1e-6  # never sells what it doesn't hold (beyond fp dust)
    assert led["cost_rupees"] >= 0.0
    # Ledger tracks shadow within rounding drag (dust + uninvested cash)
    assert led["ledger_curve"][-1] > 0


def test_pit_flag_needs_out_tag_and_ledger_matches_core():
    import sys
    sys.path.insert(0, "scripts")
    import paper_trade_10L as P
    import pytest
    with pytest.raises(ValueError):
        P.main("nifty50", 1000000.0, pit=True)  # canonical artifacts protected
    from app.core.trend_core_v4 import run_core_v4
    idx, names = _toy()
    dates = [f"2024-01-{(i % 28) + 1:02d}" for i in range(200)]
    fn_all = lambda d: {"members": set(names), "pit_status": "VERIFIED",
                        "membership_hash": "h"}
    ref = run_core_v4(idx, names, dates=dates, membership_fn=fn_all)
    led = P.replay_ledger(idx, names, None, {}, {}, 1000000.0,
                          dates=dates, membership_fn=fn_all)
    worst = max(abs(a - b) for a, b in zip(ref.eq_curve, led["shadow_curve"]))
    assert worst < 1e-9  # PIT-mode ledger still reconciles to PIT-mode core
    frozen = P.replay_ledger(idx, names, None, {}, {}, 1000000.0, dates=dates,
                             membership_fn=lambda d: {"members": set(),
                                                      "pit_status": "UNKNOWN",
                                                      "membership_hash": "u"})
    assert frozen["cash"] == 1000000.0  # frozen from bar 0: capital preserved
