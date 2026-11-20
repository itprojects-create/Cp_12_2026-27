"""Phase D market-data collector tests. Hermetic fixtures, mocked HTTP."""
from __future__ import annotations

import os

from app.data_acquisition import base as B
from app.data_acquisition import parquet as PQ
from app.data_acquisition.nse import equity as EQ
from app.data_acquisition.nse import indices as IND
from app.db import sqlite_conn


def _clean():
    B.init_tables()
    db = sqlite_conn()
    db.execute("DELETE FROM acquisition_errors WHERE source='NSE'")
    db.execute("DELETE FROM source_health WHERE source='NSE'")
    db.execute("DELETE FROM acquisition_ledger WHERE source='NSE'")


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def _fix(name):
    with open(os.path.join("tests", "fixtures", "acquisition", name), "rb") as f:
        return f.read()


def _mock(mapping):
    def get(url, **kw):
        for key, data in mapping.items():
            if key in url:
                return {"status": 200, "bytes": data, "headers": {"content-type": "text/csv"},
                        "etag": None, "last_modified": None, "not_modified": False}
        raise AssertionError(url)
    return get


def test_bhav_parse_validates_and_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    col = EQ.NseEquityEod()
    res = col.fetch(days=["2026-10-10"],
                    http_get=_mock({"cm10OCT2026bhav": _fix("bhav.csv")}))
    assert res.records_received == 3 and res.records_written == 3
    assert res.status.value == "SUCCESS"
    import pandas as pd
    df = pd.read_parquet(str(tmp_path / "norm" / "equity-eod" / "2026-10.parquet"))
    assert len(df) == 3
    infy = df[df.symbol == "INFY.NS"].iloc[0]
    assert infy["close"] == 1510.0 and infy["deliverable_qty"] == 600000
    assert infy["adjusted_research_price"] is None  # §22: unavailable, marked
    bad = df[df.symbol == "BADHIGH.NS"].iloc[0]
    assert "high_low_violation" in bad["validation_flags"]
    # idempotent re-ingest: same rows, added=0 on second fetch
    res2 = col.fetch(days=["2026-10-10"],
                     http_get=_mock({"cm10OCT2026bhav": _fix("bhav.csv")}))
    assert res2.records_received == 3


def test_bhav_schema_drift_reports_not_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    rows, rep = EQ.parse_bhav(b"SYMBOL,FOO\nA,1\n", "2026-10-10")
    assert rep["layout"] == "unknown" and rep["schema_drift"] is not None
    assert rows == []  # no SYMBOL/CLOSE -> invalid, counted


def test_indices_parse_tri_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    col = IND.NseIndices()
    res = col.fetch(days=["2026-10-10"],
                    http_get=_mock({"ind_close_all_10102026": _fix("ind_close.csv")}))
    assert res.records_received == 3 and res.records_written == 3
    import pandas as pd
    df = pd.read_parquet(str(tmp_path / "norm" / "indices" / "2026-10.parquet"))
    n50 = df[df.index_name == "NIFTY 50"].iloc[0]
    assert n50["close"] == 25050.0 and n50["tri"] == 35200.5
    assert n50["tri_source"] == "same-file"
    n500 = df[df.index_name == "NIFTY 500"].iloc[0]
    import math
    assert math.isnan(n500["tri"])  # absent TRI stays missing, never imputed


def test_ohlcv_validation_flags():
    row = {"raw_exchange_price": {"open": 10.0, "high": 9.0, "low": 11.0, "close": 10.0},
           "volume": -5, "deliverable_qty": 100, "delivery_pct": 120.0}
    flags = EQ.validate_ohlcv(row)
    assert "high_low_violation" in flags and "negative_volume" in flags
    assert "delivery_pct_range" in flags
    ok = {"raw_exchange_price": {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5},
          "volume": 100, "deliverable_qty": 40, "delivery_pct": 40.0}
    assert EQ.validate_ohlcv(ok) == []
