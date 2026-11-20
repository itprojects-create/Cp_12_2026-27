"""Day-1 honest-environment tests (prereg data/prereg_day1_environment.md). Zero tokens."""
import pytest


def test_segment_costs_and_unknown_raises():
    from app.data.environment import cost_per_side
    assert cost_per_side("nifty50") == pytest.approx(0.00105)
    assert cost_per_side("nifty500") == pytest.approx(0.0020)
    assert cost_per_side("sme") == pytest.approx(0.0150)
    with pytest.raises(ValueError):
        cost_per_side("mystery-tier")


def test_band_proxy_monotonic_and_locked():
    from app.data.environment import estimate_band, is_locked
    calm = [100 + i * 0.1 for i in range(21)]
    wild = [100 * (1.15) ** (i / 20) for i in range(21)]
    assert estimate_band(calm) <= estimate_band(wild)
    assert estimate_band([100.0]) == 0.20  # no history -> widest (conservative)
    assert is_locked(100.0, 120.05, 119.95, 120.0, 0.20) is True   # pinned, frozen
    assert is_locked(100.0, 112.0, 108.0, 110.0, 0.20) is False    # wide range
    assert is_locked(100.0, 101.0, 99.0, 100.5, 0.20) is False      # not pinned
    assert is_locked(0.0, 0.0, 0.0, 0.0, 0.20) is False              # bad data never locks


def test_calendar_window_and_missing_raises():
    from app.data.environment import load_calendar, event_gross_multiplier
    cal = load_calendar("data/event_calendar.json")
    assert event_gross_multiplier("2024-06-04", cal) == 0.5   # results day
    assert event_gross_multiplier("2024-06-02", cal) == 0.5   # t-2 edge
    assert event_gross_multiplier("2024-06-05", cal) == 0.5   # t+1 edge
    assert event_gross_multiplier("2024-06-06", cal) == 1.0   # outside
    assert event_gross_multiplier("2023-07-19", cal) == 1.0    # ordinary day
    with pytest.raises(FileNotFoundError):
        load_calendar("data/no-such-calendar.json")


def test_token_math():
    from app.data.environment import token_spend_rupees
    assert token_spend_rupees(1_200_000, 9.0) == pytest.approx(10800.0)
    assert token_spend_rupees(0, 9.0) == 0.0
    with pytest.raises(ValueError):
        token_spend_rupees(-5, 9.0)


def test_env_ledger_path_shadow_intact():
    """Env track runs alongside; shadow still equals frozen v4 exactly."""
    import sys
    sys.path.insert(0, "scripts")
    from paper_trade_10L import replay_ledger
    from app.core.trend_core_v4 import run_core_v4
    n = 120
    idx = [100 + i * 0.4 for i in range(n)]
    names = {f"T{i}.NS": [50 + i + j * 0.25 for j in range(n)] for i in range(4)}
    ohlc = {nm: {"open": list(cs), "high": [c * 1.01 for c in cs],
                 "low": [c * 0.99 for c in cs]} for nm, cs in names.items()}
    # pin one name at a +20% edge with frozen range on bar 60 -> locked
    nm0 = "T0.NS"
    ohlc[nm0]["open"][60] = 60.0
    ohlc[nm0]["high"][60] = 72.02
    ohlc[nm0]["low"][60] = 71.98
    names[nm0][60] = 72.0
    dates = [f"2024-01-{(i % 28) + 1:02d}" for i in range(n)]
    cal = {"events": [{"date": "2024-01-10", "pre": 2, "post": 1}]}
    led = replay_ledger(idx, names, None, {}, {}, 100000.0,
                        env={"ohlc": ohlc, "dates": dates, "calendar": cal})
    ref = run_core_v4(idx, names)
    worst = max(abs(a - b) for a, b in zip(ref.eq_curve, led["shadow_curve"]))
    assert worst < 1e-9
    assert "env_curve" in led and len(led["env_curve"]) == n
    assert led["locks_hit"] >= 1
    assert led["event_days"] >= 1
    assert led["cost_env"] >= 0.0
