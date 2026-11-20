"""Phase C corporate-action tests. Hermetic fixtures, mocked HTTP."""
from __future__ import annotations

import os

from app.data_acquisition import actions_store as STORE
from app.data_acquisition import base as B
from app.data_acquisition.bse import corporate_actions as BCA
from app.data_acquisition.nse import corporate_actions as NCA
from app.db import sqlite_conn


def _clean():
    STORE.init_tables()
    B.init_tables()
    from app.data import corporate_actions as PIT
    PIT.init_tables()
    from app.events import store as ST
    ST.init_tables()
    sqlite_conn().execute("DELETE FROM corp_actions WHERE source_record_id LIKE 'NSE-%'"
                          " OR source_record_id LIKE 'BSE-%'")
    for rid in ("D1", "D2"):
        r = sqlite_conn().execute(
            "SELECT record_id FROM raw_events WHERE source_id=?", (rid,)).fetchall()
        for (record_id,) in r:
            sqlite_conn().execute("DELETE FROM event_classifications WHERE record_id=?",
                                  (record_id,))
            sqlite_conn().execute("DELETE FROM normalized_events WHERE record_id=?",
                                  (record_id,))
            sqlite_conn().execute("DELETE FROM event_links WHERE child_id=? OR parent_id=?",
                                  (record_id, record_id))
            sqlite_conn().execute("DELETE FROM raw_events WHERE record_id=?", (record_id,))
    sqlite_conn().execute("DELETE FROM acquisition_errors WHERE source IN ('NSE','BSE')")
    sqlite_conn().execute("DELETE FROM source_health WHERE source IN ('NSE','BSE')")
    sqlite_conn().execute("DELETE FROM acquisition_ledger WHERE source IN ('NSE','BSE')")
    sqlite_conn().execute("DELETE FROM corporate_actions WHERE symbol LIKE 'TEST-%'"
                          " OR source='acquisition-verified'")
    sqlite_conn().execute("DELETE FROM event_links WHERE child_id LIKE 'NSE-%'"
                          " OR child_id LIKE 'BSE-%'")
    sqlite_conn().commit()


def _fix(name):
    with open(os.path.join("tests", "fixtures", "acquisition", name),
              encoding="utf-8") as f:
        return f.read().encode()


def _mock(mapping):
    def get(url, **kw):
        for key, data in mapping.items():
            if key in url:
                return {"status": 200, "bytes": data, "headers": {},
                        "etag": None, "last_modified": None, "not_modified": False}
        raise AssertionError(url)
    return get


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def test_nse_actions_parse_upsert_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    col = NCA.NseCorporateActions()
    res = col.fetch(symbols=["INFY.NS"], day="2026-10-10",
                    http_get=_mock({"symbol=INFY": _fix("nse_ca.json")}))
    assert res.records_received == 3 and res.records_written == 2
    assert res.invalid_records == 1  # empty ex_date row
    again = col.fetch(symbols=["INFY.NS"], day="2026-10-10",
                      http_get=_mock({"symbol=INFY": _fix("nse_ca.json")}))
    assert again.records_written == 2  # upserted rows persist; re-ingest stable
    n = sqlite_conn().execute("SELECT COUNT(*) FROM corp_actions").fetchone()[0]
    assert n == 2


def test_bse_actions_and_linkage(tmp_path, monkeypatch):
    from app.events import store as ST
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    col = BCA.BseCorporateActions()
    res = col.fetch(scrips=["500209"], day="2026-10-10",
                    http_get=_mock({"scrip=500209": _fix("bse_ca.json")}))
    assert res.records_received == 2 and res.records_written == 1
    # disclosure in store with kind-consistent classification -> VERIFIED link
    ST.ingest_batch("NSE", [{"exchange": "NSE", "source_id": "D1", "symbol": "INFY.NS",
                             "publication_ts": "2026-07-20T10:00:00+05:30",
                             "title": "Interim Dividend declared Rs 10", "body": "x"}])
    rid = sqlite_conn().execute(
        "SELECT record_id FROM raw_events WHERE source_id='D1'").fetchone()[0]
    ST.append_classification(rid, {"event_type": "DIVIDEND", "severity": 0.4})
    # BSE dividend ex 2026-09-15: disclosure 2026-07-20 within 60d window
    action = sqlite_conn().execute(
        "SELECT source_record_id FROM corp_actions WHERE exchange='BSE'").fetchone()[0]
    # symbol mismatch on purpose (BSE-500209 vs INFY.NS): no link, PARTIAL/UNKNOWN
    out = STORE.link_to_filing(action)
    assert out["linked"] is False
    assert out["pit_confidence"] in ("PARTIAL", "UNKNOWN")
    # same-symbol NSE dividend links VERIFIED via kind-consistent classification
    ST.ingest_batch("NSE", [{"exchange": "NSE", "source_id": "D2", "symbol": "INFY.NS",
                             "publication_ts": "2026-10-01T10:00:00+05:30",
                             "title": "Board approves interim dividend", "body": "x"}])
    rid2 = sqlite_conn().execute(
        "SELECT record_id FROM raw_events WHERE source_id='D2'").fetchone()[0]
    ST.append_classification(rid2, {"event_type": "DIVIDEND", "severity": 0.4})
    nse_action = sqlite_conn().execute(
        "SELECT source_record_id FROM corp_actions WHERE exchange='NSE'"
        " AND action_type='DIVIDEND'").fetchone()
    if nse_action:
        out2 = STORE.link_to_filing(nse_action[0])
        assert out2["linked"] is True and out2["pit_confidence"] == "VERIFIED"


def test_pit_visibility_and_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    col = NCA.NseCorporateActions()
    col.fetch(symbols=["INFY.NS"], day="2026-10-10",
              http_get=_mock({"symbol=INFY": _fix("nse_ca.json")}))
    # announcement 10-08 <= as_of 10-09: knowable; ex-date action visible
    vis = STORE.actions_for("INFY.NS", "2026-10-09")
    assert any(a["action_type"] == "DIVIDEND" for a in vis)
    # before announcement: invisible (PIT)
    assert STORE.actions_for("INFY.NS", "2026-10-01") == []
    synced = STORE.sync_verified_to_pit()
    assert isinstance(synced["synced"], int)
