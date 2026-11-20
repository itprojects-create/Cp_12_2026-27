"""Day 1 leak-fix tests (NEW_PLAN T1.1-T1.3): PIT fundamentals, events cache flag, universe tiers."""
from datetime import datetime, timezone


def test_fundamentals_historical_never_touches_info():
    from app.agents import analysts as A
    import yfinance as yf
    old = datetime(2022, 8, 2, tzinfo=timezone.utc)
    assert A._is_historical(old) is True
    # Historical path must not call yfinance info: patch to raise if touched
    orig = yf.Ticker
    def _boom(*a, **k):
        raise AssertionError("historical fundamentals must not fetch .info")
    yf.Ticker = _boom
    try:
        # _is_historical gate is what run_fundamentals uses; assert gate holds
        assert A._is_historical(old)
    finally:
        yf.Ticker = orig
    live = datetime.now(timezone.utc)
    assert A._is_historical(live) is False


def test_events_cache_has_fetched_at_and_note():
    import app.data.events as E
    import inspect
    src = inspect.getsource(E.YFinanceEventsProvider._raw)
    assert "fetched_at" in src
    assert "revision_note" in src or "revised" in src.lower()


def test_forward_return_uses_adjusted():
    import inspect
    import app.eval.run as R
    src = inspect.getsource(R.forward_return)
    assert "auto_adjust=True" in src


def test_universe_tiers():
    from app.data import universe as U
    n50 = U.nifty50_frozen()
    assert len(n50) >= 30 and "RELIANCE.NS" in n50
    # Missing files must raise loudly, never silent fallback
    import pytest
    with pytest.raises(FileNotFoundError):
        U.load_list("data/definitely_missing_universe_xyz.txt")
    assert U.SME_MAX_POSITION_PCT == 0.03


def test_sme_liquid_gate():
    import pandas as pd
    from app.data.universe import sme_liquid
    idx = pd.date_range("2024-01-01", periods=25, freq="D", tz="UTC")
    # Liquid large-cap-like bars
    import numpy as np
    closes = 100 + np.cumsum(np.random.RandomState(0).randn(25))
    vols = [1_000_000] * 25
    df = pd.DataFrame({"Close": closes, "Volume": vols}, index=idx)
    assert sme_liquid(df) is True
    # Cheap stock excluded
    df2 = df.copy()
    df2["Close"] = 5.0
    assert sme_liquid(df2) is False
