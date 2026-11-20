"""Phase E institutional collector tests. Hermetic fixtures, mocked HTTP."""
from __future__ import annotations

import os

from app.data_acquisition import base as B
from app.data_acquisition import parquet as PQ
from app.data_acquisition.cdsl import fpi as CDSL
from app.data_acquisition.nse import deals as DEALS
from app.data_acquisition.nse import institutional as INST
from app.db import sqlite_conn


def _clean():
    B.init_tables()
    db = sqlite_conn()
    for t in ("acquisition_errors", "source_health", "acquisition_ledger", "backfill_state"):
        db.execute(f"DELETE FROM {t} WHERE source IN ('NSE','CDSL') OR dataset LIKE '%provisional%'"
                   if t != "backfill_state" else "DELETE FROM backfill_state WHERE dataset LIKE 'TEST-%'")
    sqlite_conn().commit()


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


def test_bulk_parse_and_store(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    col = DEALS.NseDeals()
    res = col.fetch(days=["2026-10-10"], kinds=("BULK",),
                    http_get=_mock({"bulk.csv": _fix("bulk.csv")}))
    assert res.records_received == 3 and res.records_written == 3
    import pandas as pd
    df = pd.read_parquet(str(tmp_path / "norm" / "bulk-block-deals" / "2026-10.parquet"))
    infy = df[(df.symbol == "INFY.NS") & (df.side == "BUY")].iloc[0]
    assert infy["quantity"] == 500000 and infy["client_name"] == "ABC FUNDS"
    assert infy["deal_type"] == "BULK"  # client names verbatim, no inference labels
    src = open("app/data_acquisition/nse/deals.py", encoding="utf-8").read().lower()
    assert "smart_money" not in src and "signal" not in src and "alpha" not in src


def test_deals_partial_on_kind_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))

    def get(url, **kw):
        if "bulk.csv" in url:
            return _mock({"bulk.csv": _fix("bulk.csv")})(url, **kw)
        from app.data_acquisition import http as H
        raise H.HttpError("gone", code=404)

    res = DEALS.NseDeals().fetch(days=["2026-10-10"], http_get=get)
    assert res.status == B.FetchStatus.PARTIAL and res.records_received == 3


def test_fii_dii_provisional_never_final(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    col = INST.NseFlows()
    res = col.fetch(day="2026-10-10",
                    http_get=_mock({"fiidiiTradeReco": _fix("fiidii.json")}))
    assert res.records_received == 2 and res.records_written == 2  # NOPE excluded
    import pandas as pd
    df = pd.read_parquet(str(tmp_path / "norm" / "fii-dii-provisional" / "2026-10.parquet"))
    assert set(df["status"]) == {"PROVISIONAL"}
    fii = df[df.category == "FII"].iloc[0]
    assert fii["net_cr"] == 500.25


def test_cdsl_manual_import_and_cross_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    src = os.path.join("tests", "fixtures", "acquisition", "cdsl_fpi.csv")
    col = CDSL.CdslFpi()
    res = col.import_file(src, day="2026-10-16")
    assert res.records_received == 2 and res.records_written == 2
    import pandas as pd
    df = pd.read_parquet(str(tmp_path / "norm" / "fpi-final" / "2026-10.parquet"))
    assert set(df["status"]) == {"FINAL"}
    auto = col.fetch()
    assert auto.status == B.FetchStatus.SOURCE_UNAVAILABLE
    assert auto.source_failures[0]["status"] == "SUBSCRIPTION_REQUIRED"
    assert CDSL.compare_provisional_final(500.25, 500.25)["grade"] == "MATCH"
    assert CDSL.compare_provisional_final(500.25, 600.0)["grade"] == "MINOR_DIFFERENCE"
    assert CDSL.compare_provisional_final(500.25, 5000.0)["grade"] == "CONFLICT"
