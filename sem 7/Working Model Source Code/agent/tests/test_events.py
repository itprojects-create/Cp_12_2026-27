"""Event diet tests: PIT filtering, surprise math, breakout detector, honest gaps. Zero tokens."""
from __future__ import annotations
import pandas as pd
import pytest
from datetime import datetime, timezone

from app.data import events as E

AS_OF = datetime(2024, 6, 10, tzinfo=timezone.utc)

class _Ticker:
    """Stub yfinance.Ticker: one reported beat, one scheduled result, one div, one split."""
    def __init__(self, *a, **k): pass
    @property
    def earnings_dates(self):
        return pd.DataFrame(
            {"EPS Estimate": [10.0, 11.0, None], "Reported EPS": [12.0, float("nan"), float("nan")],
             "Surprise(%)": [20.0, float("nan"), float("nan")]},
            index=[pd.Timestamp("2024-05-01"), pd.Timestamp("2024-06-25"), pd.Timestamp("2024-09-01")])
    @property
    def dividends(self):
        return pd.Series([5.0, 6.0], index=[pd.Timestamp("2024-04-01"), pd.Timestamp("2025-01-01")])
    @property
    def splits(self):
        return pd.Series([2.0], index=[pd.Timestamp("2024-03-01")])

@pytest.fixture(autouse=True)
def _yf(monkeypatch, tmp_path):
    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", _Ticker)
    monkeypatch.setattr(E, "CACHE_DIR", str(tmp_path))

def test_reported_surprise_and_pit():
    items = E.YFinanceEventsProvider().events("X.NS", AS_OF)
    kinds = {(i.kind, i.date) for i in items}
    assert ("earnings_reported", "2024-05-01") in kinds
    beat = next(i for i in items if i.kind == "earnings_reported")
    assert beat.surprise_pct == 20.0 and beat.assumed is False
    # future dividend + far earnings must NOT leak through
    assert not any(i.date == "2025-01-01" for i in items)
    assert not any(i.date == "2024-09-01" for i in items)
    # near scheduled result (15d out, inside 21d window) IS usable, flagged assumed
    up = [i for i in items if i.kind == "earnings_upcoming"]
    assert len(up) == 1 and up[0].assumed is True
    assert up[0].known_at <= AS_OF.isoformat()
    # actions inside window pass PIT
    assert ("dividend", "2024-04-01") in kinds and ("split", "2024-03-01") in kinds

def test_caches_raw_but_filters_per_asof():
    p = E.YFinanceEventsProvider()
    n1 = len(p.events("X.NS", AS_OF))
    early = datetime(2024, 4, 15, tzinfo=timezone.utc)
    items = p.events("X.NS", early)  # cache may exist; filter must still apply
    assert not any(i.kind == "earnings_reported" for i in items)
    assert n1 > len(items)

def test_breakout_detector():
    idx = pd.date_range("2024-04-01", periods=70, freq="B", tz="UTC")
    closes = [100.0] * 69 + [120.0]
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                       "Close": closes, "Volume": 1_000_000}, index=idx)
    df.loc[df.index[-1], "High"] = 120.5
    df.loc[df.index[-1], "Volume"] = 3_000_000
    from app.agents.features import describe
    txt = describe(df)
    assert "breakout20d=YES" in txt and "volx=2.73" in txt

def test_broker_gaps_are_explicit():
    p = E.YFinanceEventsProvider()
    for fn in (p.fii_dii_flows, p.delivery_pct, p.option_chain):
        with pytest.raises(E.NotConfigured):
            fn("X.NS", AS_OF)
