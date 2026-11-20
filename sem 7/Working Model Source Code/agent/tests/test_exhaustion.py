"""Exhaustion gauge tests: no-lookahead, mutual exclusivity, known -10% drop. Zero tokens."""
from __future__ import annotations
import pandas as pd

from app.agents.features import exhaustion_features, exhaustion_line

def _df(n: int = 120, last_close: float = 100.0, drop_pct_5d: float = 0.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    closes = [100.0] * n
    if drop_pct_5d:
        closes[-1] = closes[-6] * (1 + drop_pct_5d / 100)
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": closes, "Volume": 1_000_000}, index=idx)

def test_no_lookahead_future_rows_ignored():
    base = _df(120, drop_pct_5d=0.0)
    asof = 99
    a = exhaustion_features(base, asof)
    longer = pd.concat([base, _df(30).assign(
        **{"Close": 999.0, "High": 999.0, "Low": 999.0})]).reset_index(drop=True)
    b = exhaustion_features(longer, asof)
    assert a == b  # future rows after asof_idx change nothing

def test_mutually_exclusive_and_threshold():
    assert exhaustion_features(_df(120), 119)["flush_flag"] is False
    out = exhaustion_features(_df(120), 119)
    assert out["blowoff_flag"] is False
    assert not (out["flush_flag"] and out["blowoff_flag"])

def test_known_minus_ten_pct_drop_flags_flush():
    df = _df(120, drop_pct_5d=-10.0)
    out = exhaustion_features(df, 119)
    assert out["flush_flag"] is True and out["blowoff_flag"] is False
    assert out["ret_5d_pct"] == -10.0
    assert "FLUSH" in exhaustion_line(df)

def test_short_history_falls_back():
    out = exhaustion_features(_df(30), 29)
    assert out["exhaustion_threshold_pct"] == 8.0

def test_threshold_is_80th_percentile_of_own_history():
    import math
    n = 150
    idx = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    closes = [100.0 + 5.0 * math.sin(i / 3.0) + 0.1 * i for i in range(n)]
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                       "Close": closes, "Volume": 1_000_000}, index=idx)
    out = exhaustion_features(df, n - 1)
    hist = df["Close"].iloc[:n - 1]
    r5 = hist.pct_change(5).abs().dropna() * 100
    q80 = round(max(float(r5.quantile(0.80)), 1.0), 2)
    q90 = round(max(float(r5.quantile(0.90)), 1.0), 2)
    assert q80 != q90, "fixture must discriminate 80th from 90th"
    assert out["exhaustion_threshold_pct"] == q80
