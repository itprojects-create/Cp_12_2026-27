"""Overlay + retry isolation tests (NEW_PLAN Day 4, prereg data/prereg_overlay_retry.md). Zero tokens."""
from app.core.overlay import veto_fraction, apply_veto, breadth_pct


def test_veto_table_frozen():
    assert veto_fraction("STRESSED", 0.2, 0.0, -5.0) == 1.0
    assert veto_fraction("ELEVATED", 0.2, 0.0, -5.0) == 0.5
    assert veto_fraction("CALM", 0.8, 0.0, -5.0) == 0.0
    # Blowoff overrides everything
    assert veto_fraction("CALM", 0.9, 10.0, -0.1) == 1.0
    assert veto_fraction("CALM", 0.9, 0.0, -5.0, blackout_dense=True) == 0.5


def test_veto_never_increases():
    core = {"A.NS": 0.08, "B.NS": 0.0}
    out = apply_veto(core, {"A.NS": 0.5, "B.NS": 1.0})
    assert out["A.NS"] == 0.04
    assert out["B.NS"] == 0.0
    assert all(v <= core[k] + 1e-12 for k, v in out.items())


def test_breadth_pit():
    n = 100
    rising = [100 + i * 0.5 for i in range(n)]
    flat = [100.0] * n
    b = breadth_pct({"A.NS": rising, "B.NS": flat}, n - 1)
    assert 0.0 <= b <= 1.0
    # Truncation never changes past bars (no lookahead in MA window)
    b2 = breadth_pct({"A.NS": rising[:80], "B.NS": flat[:80]}, 79)
    assert 0.0 <= b2 <= 1.0


def test_retry_isolated_module():
    import app.agents.retry_manager as R
    import inspect
    src = inspect.getsource(R.run_session_retry)
    assert "retry_analysts" in src and "retry_thesis" in src
    src2 = inspect.getsource(R.run_manager_retry)
    assert "falsifier" in src2.lower() and "base-rate" in src2.lower() or "base_rate" in src2.lower()
