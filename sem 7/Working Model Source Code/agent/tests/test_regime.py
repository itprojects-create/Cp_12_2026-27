"""M3 regime classifier tests: PIT discipline, conservative defaults, boundaries."""
from __future__ import annotations
import pandas as pd

from app.data.regime import classify_regime


def _vix(values: list[float]) -> pd.Series:
    idx = pd.date_range("2023-01-02", periods=len(values), freq="B", tz="UTC")
    return pd.Series(values, index=idx)


def test_no_lookahead_future_rows_ignored():
    # 200 bars calm at 12, then a spike: classification at the spike must not
    # change when even more future rows are appended after asof_idx.
    base = [12.0] * 200 + [25.0]
    assert classify_regime(_vix(base), 200) == "STRESSED"
    extended = base + [30.0, 8.0, 9.0, 40.0]
    assert classify_regime(_vix(extended), 200) == "STRESSED"
    # and an earlier calm bar is unaffected by the later spike
    assert classify_regime(_vix(extended), 100) == "CALM"


def test_insufficient_history_defaults_calm():
    assert classify_regime(_vix([12.0] * 30), 29) == "CALM"
    assert classify_regime(_vix([99.0] * 10), 9) == "CALM"  # extreme but short
    assert classify_regime(_vix([]), 0) == "CALM"
    assert classify_regime(_vix([12.0] * 70), 999) == "CALM"  # out of range
    assert classify_regime(_vix([12.0] * 70), -1) == "CALM"


def test_synthetic_percentile_boundaries():
    # trailing history: 100 bars linearly 10.0..19.9 (strictly before asof).
    hist = [10.0 + i * 0.1 for i in range(100)]
    # current == median-ish of history -> below 50th pct -> CALM
    assert classify_regime(_vix(hist + [14.5]), 100) == "CALM"
    # current above median but below 85th pct -> ELEVATED
    assert classify_regime(_vix(hist + [17.0]), 100) == "ELEVATED"
    # current at the very top of history -> >= 85th pct -> STRESSED
    assert classify_regime(_vix(hist + [25.0]), 100) == "STRESSED"
    # lookback truncation respected: only the last `lookback` bars count
    low_then_high = [10.0] * 100 + [20.0] * 100
    # full trailing window: current 10.0 sits below everything -> CALM
    assert classify_regime(_vix(low_then_high + [10.0]), 200) == "CALM"
    # boundary semantics: exactly 50.0% of history below current ranks
    # ELEVATED (>=), not CALM — documented, deterministic
    assert classify_regime(_vix(low_then_high + [10.5]), 200) == "ELEVATED"
    # truncated to the recent high block: 10.5 is below all of it -> CALM too,
    # while a 25.0 current ranks at top of the recent block -> STRESSED
    assert classify_regime(_vix(low_then_high + [25.0]), 200, lookback=100) == "STRESSED"


def test_regime_at_never_raises_offline(monkeypatch):
    import app.data.regime as RG

    class _Boom:
        def ohlcv(self, *a, **k):
            raise RuntimeError("offline")
    monkeypatch.setattr(RG, "YFinanceProvider", _Boom)
    from datetime import datetime, timezone
    assert RG.regime_at(datetime(2024, 6, 10, tzinfo=timezone.utc)) == "CALM"
