"""Core v4 invariant tests (prereg data/prereg_core_v4.md). Zero tokens."""


def _rising(n, start=100.0, step=0.5):
    out, v = [], start
    for _ in range(n):
        out.append(v)
        v += step
    return out


def test_topk_bounded():
    from app.core.trend_core_v4 import run_core_v4, TOP_K
    assert TOP_K == 50  # frozen by prereg
    n = 200
    idx = _rising(n)
    names = {f"N{i}.NS": _rising(n, 100 + i * 0.1) for i in range(80)}
    r = run_core_v4(idx, names)
    assert r.exposure <= 1.00 + 1e-9
    assert r.n_days == n


def test_prefix_invariance():
    from app.core.trend_core_v4 import run_core_v4
    n = 200
    idx = _rising(n)
    names = {f"N{i}.NS": _rising(n, 100 + i) for i in range(10)}
    full = run_core_v4(idx, names)
    trunc = run_core_v4(idx[:150], {k: v[:150] for k, v in names.items()})
    assert full.eq_curve[:150] == trunc.eq_curve  # past bars never change


def test_bench_math_corrected():
    from app.core.trend_core_v4 import bench_cagr_corrected
    # Single name: bench == its own buy-hold CAGR exactly
    cs = [100.0, 110.0, 121.0]
    import math
    expect = (121.0 / 100.0) ** (1 / (3 / 252.0)) - 1
    assert abs(bench_cagr_corrected({"A.NS": cs}, 3) - expect) < 1e-9
    # 391-name scale: finite, no explosion
    names = {f"N{i}.NS": [100.0, 100.0 * (1 + (i % 7) * 0.5)] for i in range(391)}
    b = bench_cagr_corrected(names, 252)
    assert 0.0 < b < 10.0


def test_veto_shrink_only_and_gross_cap():
    from app.core.trend_core_v4 import run_core_v4
    n = 200
    idx = _rising(n)
    names = {f"N{i}.NS": _rising(n, 100 + i) for i in range(60)}
    vix = [14.0] * 100 + [40.0] * 100
    r = run_core_v4(idx, names, vix_closes=vix)
    assert r.exposure <= 1.00 + 1e-9
    assert r.total_cost <= r.n_switches * 0.00105 * 0.10 + 1e-9
