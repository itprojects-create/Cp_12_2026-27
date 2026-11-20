"""Phase F derivatives tests. Hermetic fixtures, mocked HTTP."""
from __future__ import annotations

import os

from app.data_acquisition import base as B
from app.data_acquisition import features_pcr as PCR
from app.data_acquisition import parquet as PQ
from app.data_acquisition.nse import fno as FNO
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
                return {"status": 200, "bytes": data, "headers": {},
                        "etag": None, "last_modified": None, "not_modified": False}
        raise AssertionError(url)
    return get


def test_fo_bhav_parse_and_negative_oi_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    col = FNO.NseFno()
    res = col.fetch(days=["2026-10-10"],
                    http_get=_mock({"fo10OCT2026bhav": _fix("fo_bhav.csv")}))
    assert res.records_received == 6 and res.records_written == 6
    import pandas as pd
    df = pd.read_parquet(str(tmp_path / "norm" / "fno-bhavcopy" / "2026-10.parquet"))
    fut = df[(df.symbol == "NIFTY") & (df.instrument_type == "FUTIDX")].iloc[0]
    assert fut["settle_price"] == 25060.0 and fut["open_interest"] == 200000
    # exact source field names preserved in raw tables (§31: no renaming)
    assert "settle_price" in df.columns and "change_in_oi" in df.columns


def test_participant_oi_volume_separate_datasets(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    monkeypatch.setattr(PQ, "NORMALIZED_ROOT", str(tmp_path / "norm"))
    oi = FNO.NseParticipantOi().fetch(
        days=["2026-10-10"],
        http_get=_mock({"participant_wise_open_interest": _fix("participant_oi.csv")}))
    vol = FNO.NseParticipantVol().fetch(
        days=["2026-10-10"],
        http_get=_mock({"participant_wise_trading_volume": _fix("participant_oi.csv")}))
    assert oi.records_received == 2 and vol.records_received == 2
    import pandas as pd
    oi_df = pd.read_parquet(str(tmp_path / "norm" / "participant-oi" / "2026-10.parquet"))
    vol_df = pd.read_parquet(str(tmp_path / "norm" / "participant-volume" / "2026-10.parquet"))
    assert "src_index_puts_long" in oi_df.columns  # exact source names kept
    assert oi_df[oi_df.client_type == "FII"].iloc[0]["src_index_futures_long"] == 100000
    # OI and volume never merged (§30)
    assert oi.records_written == 2 and vol.records_written == 2


def test_pcr_definitions_versioned_and_safe():
    rows, _ = FNO.parse_fo_bhav(_fix("fo_bhav.csv"), "2026-10-10")
    out = PCR.compute(rows, underlying="NIFTY", day_iso="2026-10-10")
    assert out["definition_version"] == "PCR_DEFS_V1"
    assert out["PCR_OI_ALL"] == (450000 + 150000) / (300000 + 100000)
    assert out["PCR_OI_NEAR_EXPIRY"] == 450000 / 300000
    assert out["nearest_expiry"] == "2026-10-29" and out["n_futures"] == 1
    empty = PCR.compute([], underlying="NIFTY")
    assert empty["PCR_OI_ALL"] is None  # zero denominator -> None, never inf
    for key in ("PCR_OI_ALL", "PCR_OI_NEAR_EXPIRY", "PCR_VOLUME_ALL"):
        assert set(PCR.DEFINITIONS[key]) >= {"expiry_inclusion", "strike_inclusion",
                                             "universe", "timestamp"}
