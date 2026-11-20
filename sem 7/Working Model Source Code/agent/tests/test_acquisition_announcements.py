"""Phase B announcement collector tests. Hermetic fixtures, mocked HTTP."""
from __future__ import annotations

import json
import os

import pytest

from app.data_acquisition import base as B
from app.data_acquisition import attachments as ATT
from app.data_acquisition.bse import announcements as BSE
from app.data_acquisition.nse import announcements as NSE
from app.db import sqlite_conn
from app.events import store as ST


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RAW_ROOT", str(tmp_path / "raw"))
    ST.init_tables()
    yield
    db = sqlite_conn()
    for t in ("event_classifications", "event_links", "normalized_events",
              "raw_events", "event_batches"):
        col = {"event_classifications": "record_id", "event_links": "child_id",
               "normalized_events": "record_id", "raw_events": "record_id",
               "event_batches": "batch_id"}[t]
        db.execute(f"DELETE FROM {t} WHERE {col} LIKE 'EV-%' OR {col} LIKE 'BATCH-%'")
    db.execute("DELETE FROM acquisition_errors WHERE source IN ('NSE','BSE')")
    db.execute("DELETE FROM source_health WHERE source IN ('NSE','BSE')")
    db.execute("DELETE FROM acquisition_ledger WHERE source IN ('NSE','BSE','attachments')")
    db.commit()


def _fix(name):
    with open(os.path.join("tests", "fixtures", "acquisition", name),
              encoding="utf-8") as f:
        return f.read().encode()


def _mock(payload_map):
    def get(url, **kw):
        for key, data in payload_map.items():
            if key in url:
                return {"status": 200, "bytes": data, "headers": {"content-type": "application/json"},
                        "etag": None, "last_modified": None, "not_modified": False}
        raise AssertionError(f"unexpected url {url}")
    return get


def test_nse_success_writes_raw_and_store():
    col = NSE.NseAnnouncements()
    res = col.fetch(symbols=["INFY.NS"], day="2026-10-10",
                    http_get=_mock({"symbol=INFY": _fix("nse_ann.json")}))
    assert res.status == B.FetchStatus.SUCCESS
    assert res.records_received == 2 and res.records_written == 2
    assert len(res.raw_hashes) == 1 and res.batch_id.startswith("NSE-announcements-")
    assert ST.store_stats()["raw"] == 2
    # raw artifact retained with sidecar under the day-partitioned raw root
    from app.data_acquisition import base as BB
    import glob as _g
    metas = _g.glob(os.path.join(BB.RAW_ROOT, "NSE", "announcements", "2026", "10",
                                 "10", "*.meta.json"))
    assert len(metas) == 1
    meta = json.load(open(metas[0], encoding="utf-8"))
    assert meta["ingestion_mode"] == "LIVE" and meta["first_seen_live"] is True


def test_nse_duplicate_and_partial_and_invalid():
    col = NSE.NseAnnouncements()
    get = _mock({"symbol=INFY": _fix("nse_ann.json")})
    col.fetch(symbols=["INFY.NS"], day="2026-10-10", http_get=get)
    r2 = col.fetch(symbols=["INFY.NS"], day="2026-10-10", http_get=get)
    assert r2.duplicates == 2 and r2.records_written == 0
    assert ST.store_stats()["raw"] == 2  # no second rows

    def mixed(url, **kw):
        if "symbol=BAD" in url:
            return {"status": 200, "bytes": b"not json{{", "headers": {},
                    "etag": None, "last_modified": None, "not_modified": False}
        return get(url, **kw)

    r3 = col.fetch(symbols=["INFY.NS", "BAD.NS"], day="2026-10-10", http_get=mixed)
    assert r3.status == B.FetchStatus.PARTIAL
    assert r3.invalid_records == 1


def test_nse_blocked_status_mapping():
    from app.data_acquisition import http as H
    col = NSE.NseAnnouncements()

    def blocked(url, **kw):
        raise H.HttpError("forbidden", code=403)

    res = col.fetch(symbols=["X.NS"], day="2026-10-10", http_get=blocked)
    assert res.status == B.FetchStatus.SOURCE_UNAVAILABLE
    assert res.source_failures and res.source_failures[0]["status"] == "SOURCE_BLOCKED"


def test_bse_parse_and_isin_cross_link():
    bcol = BSE.BseAnnouncements()
    res = bcol.fetch(scrips=["500209"], day="2026-10-10",
                     http_get=_mock({"strScrip=500209": _fix("bse_ann.json")}))
    assert res.records_received == 2 and res.records_written == 2
    # NSE row with the same ISIN + date links deterministically
    ST.ingest_batch("NSE", [{"exchange": "NSE", "source_id": "N1", "symbol": "INFY.NS",
                             "publication_ts": "2026-10-08T16:05:00+05:30",
                             "title": "Board Meeting Intimation for Results",
                             "body": "x", "isin": "INE009A01021"}])
    links = BSE.cross_link_bse_nse()
    assert links["linked"] == 1
    assert links["ambiguous_unlinked"] == 0 and links["no_match"] == 0
    assert links["no_isin_unlinkable"] == 1
    # BSE symbols stay exchange-scoped (never rewritten to .NS)
    syms = {r[0] for r in sqlite_conn().execute(
        "SELECT symbol FROM raw_events WHERE exchange='BSE'").fetchall()}
    assert syms == {"BSE-500209"}


def test_attachments_allowlist():
    refused = ATT.fetch_attachment("https://evil.example/x.pdf", "2026-10-10")
    assert refused["status"] == "REFUSED_HOST"
    assert ATT.allowed("https://nsearchives.nseindia.com/corporate/a.pdf") is True


def test_no_second_event_store():
    import pathlib
    for mod in ("app/data_acquisition/nse/announcements.py",
                "app/data_acquisition/bse/announcements.py"):
        src = pathlib.Path(mod).read_text(encoding="utf-8")
        assert "CREATE TABLE" not in src
        assert "sqlite_conn().execute" not in src or "INSERT INTO raw_events" not in src
