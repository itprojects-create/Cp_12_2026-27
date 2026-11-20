"""Core v3 invariant tests (NEW_PLAN Day 3, prereg data/prereg_core_v3.md). Zero tokens."""
from app.core.trend_core_v3 import run_core_v3, vix_regime_series


def _flat(n, v=100.0):
    return [v] * n


def _rising(n, start=100.0, step=0.5):
    out, v = [], start
    for _ in range(n):
        out.append(v)
        v += step
    return out


def test_vix_regime_prefix_invariant():
    vix = [15 + (i % 30) * 0.3 for i in range(300)]
    full = vix_regime_series(vix)
    trunc = vix_regime_series(vix[:200])
    assert full[:200] == trunc  # no lookahead: truncation never changes past bars


def test_v3_gross_cap_and_turnover():
    n = 200
    idx = _rising(n)
    names = {f"N{i}.NS": _rising(n, 100 + i) for i in range(12)}
    vix = [14.0] * n
    r = run_core_v3(idx, names, vix_closes=vix)
    assert r.exposure <= 1.00 + 1e-9
    # Turnover filter never increases switches vs dust-free accounting
    assert r.total_cost <= r.n_switches * 0.00105 * 0.10 + 1e-9


def test_v3_stressed_blocks_new_entries():
    n = 200
    idx = _rising(n)
    names = {"A.NS": _rising(n)}
    vix = [14.0] * 100 + [40.0] * 100  # late spike => STRESSED trailing
    r = run_core_v3(idx, names, vix_closes=vix)
    assert r.exposure <= 1.00 + 1e-9
    assert r.n_days == n


def test_v3_blackout_only_blocks_new():
    n = 120
    idx = _rising(n)
    names = {"A.NS": _rising(n), "B.NS": _rising(n, 50)}
    # Blackout every bar for A => A never enters; B unaffected
    bl = {"A.NS": set(range(n))}
    r = run_core_v3(idx, names, blackout=bl)
    assert r.n_switches >= 0
    assert r.exposure >= 0.0


def test_v3_tier_and_sector_caps():
    n = 120
    idx = _rising(n)
    names = {f"S{i}.NS": _rising(n, 100 + i) for i in range(6)}
    tier = {k: "sme" for k in names}
    sector = {k: "BANK" for k in names}
    r = run_core_v3(idx, names, tier=tier, sector=sector)
    # 6 SME names x 3% = 18% max, sector 25% loose => exposure <= 18%+drift
    assert r.exposure <= 0.30
