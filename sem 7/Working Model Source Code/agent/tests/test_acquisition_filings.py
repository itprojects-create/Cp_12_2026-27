"""Phase G filings/XBRL tests. Hermetic fixtures; PIT leakage covered."""
from __future__ import annotations

import os

from app.data_acquisition import base as B
from app.data_acquisition import filings as FIL
from app.data_acquisition import xbrl as XBRL
from app.data_acquisition.nse import filings as NF
from app.db import sqlite_conn


def _clean():
    FIL.init_tables()
    B.init_tables()
    db = sqlite_conn()
    db.execute("DELETE FROM filings WHERE symbol LIKE 'TEST-%' OR symbol='INFY.NS'")
    db.execute("DELETE FROM acquisition_ledger WHERE source='NSE'")
    db.execute("DELETE FROM acquisition_errors WHERE source='NSE'")
    db.execute("DELETE FROM source_health WHERE source='NSE'")


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def _fix(name):
    with open(os.path.join("tests", "fixtures", "acquisition", name), "rb") as f:
        return f.read()


def test_xbrl_parses_known_fields_only():
    parsed = XBRL.parse_xbrl(_fix("result.xml"))
    assert parsed["facts"]["revenue"]["value"] == 50000
    assert parsed["facts"]["pat"]["value"] == 8000
    assert parsed["facts"]["eps_basic"]["value"] == 42.5
    assert "NotAField" not in str(parsed["facts"])  # unknown tags ignored
    bad = XBRL.parse_xbrl(b'<xbrl xmlns:ind="urn:x"><ind:Revenue contextRef="C1">abc'
                          b'</ind:Revenue></xbrl>')
    assert any("non-numeric" in w for w in bad["warnings"])  # known field, bad value
    assert parsed["namespace"] != ""
    shp = XBRL.parse_xbrl(_fix("shareholding.xml"))
    assert shp["facts"]["promoter_pct"]["value"] == 14.2
    assert shp["facts"]["shares_outstanding"]["value"] == 4140000000
    assert XBRL.parse_xbrl(b"<broken")["facts"] == {}  # drift-safe, never raises


def test_filing_revision_chain_and_pit(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    xml = _fix("result.xml")
    r1 = FIL.ingest_filing("INFY.NS", "financial-results", "2026-04-01", "2026-06-30",
                           "2026-08-07T17:42:00+05:30", xbrl_bytes=xml)
    assert r1["revision_n"] == 1 and r1["duplicate"] is False
    # period-end (06-30) is NOT the eligibility clock: invisible in July
    assert FIL.visible_filing("INFY.NS", "financial-results", "2026-06-30",
                              "2026-07-15T00:00:00+00:00") is None
    # eligible after broadcast + buffer (08-07 17:42 IST + 15min)
    vis = FIL.visible_filing("INFY.NS", "financial-results", "2026-06-30",
                             "2026-08-08T00:00:00+00:00")
    assert vis is not None and vis["facts"]["revenue"] == 50000
    # same broadcast re-ingested -> idempotent duplicate
    r1b = FIL.ingest_filing("INFY.NS", "financial-results", "2026-04-01", "2026-06-30",
                            "2026-08-07T17:42:00+05:30", xbrl_bytes=xml)
    assert r1b["duplicate"] is True
    # revised broadcast -> new revision, old preserved; pre-revision as_of sees v1
    r2 = FIL.ingest_filing("INFY.NS", "financial-results", "2026-04-01", "2026-06-30",
                           "2026-09-01T10:00:00+05:30", xbrl_bytes=xml)
    assert r2["revision_n"] == 2
    assert FIL.visible_filing("INFY.NS", "financial-results", "2026-06-30",
                              "2026-08-08T00:00:00+00:00")["revision"] == 1
    assert FIL.visible_filing("INFY.NS", "financial-results", "2026-06-30",
                              "2026-09-02T00:00:00+00:00")["revision"] == 2


def test_fundamentals_as_of_never_leaks_period_end():
    xml = _fix("result.xml")
    FIL.ingest_filing("INFY.NS", "financial-results", "2026-04-01", "2026-06-30",
                      "2026-08-07T17:42:00+05:30", xbrl_bytes=xml)
    early = FIL.fundamentals_as_of("INFY.NS", "2026-07-01T00:00:00+00:00")
    assert early["periods"] == []  # quarter ended, unpublished -> invisible
    late = FIL.fundamentals_as_of("INFY.NS", "2026-08-08T00:00:00+00:00")
    assert len(late["periods"]) == 1 and "period-end never gates" in late["pit_note"]


def test_manual_import_and_sanity_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    col = NF.NseFilings()
    p = tmp_path / "res.xml"
    p.write_bytes(_fix("result.xml"))
    out = col.import_file("TEST-INFY.NS", "financial-results", "2026-04-01",
                          "2026-06-30", "2026-08-07T17:42:00+05:30", str(p))
    assert out["revision_n"] == 1 and out["sanity"] == []
    bad = col.import_file("TEST-INFY.NS", "financial-results", "2026-06-30",
                          "2026-04-01", "2026-08-07T17:42:00+05:30", str(p))
    assert "invalid_period" in bad["sanity"]  # detected, figures untouched
    # figures never altered to fit identities
    assert FIL.visible_filing("TEST-INFY.NS", "financial-results", "2026-06-30",
                              "2026-08-08T00:00:00+00:00")["facts"]["revenue"] == 50000
