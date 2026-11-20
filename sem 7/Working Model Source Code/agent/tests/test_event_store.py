"""P1 immutable-ingestion tests (§78 raw-store + identity excerpts). Hermetic."""
from __future__ import annotations

import pytest

from app.db import sqlite_conn
from app.events import store as ST
from app.events import textnorm as TN


@pytest.fixture(autouse=True)
def _clean():
    ST.init_tables()
    yield
    db = sqlite_conn()
    db.execute("DELETE FROM event_classifications WHERE record_id LIKE 'EV-%'")
    db.execute("DELETE FROM event_links WHERE child_id LIKE 'EV-%'")
    db.execute("DELETE FROM normalized_events WHERE record_id LIKE 'EV-%'")
    db.execute("DELETE FROM raw_events WHERE record_id LIKE 'EV-%'")
    db.execute("DELETE FROM event_batches WHERE batch_id LIKE 'BATCH-TEST-%'")
    db.execute("DELETE FROM source_failures WHERE detail LIKE 'TEST-%'")
    db.commit()


def _raw(symbol="INFY.NS", title="Board Meeting Intimation", body="Body here",
         pub="2026-10-01T10:00:00+00:00", sid="SRC-1", exchange="NSE"):
    return {"exchange": exchange, "source_id": sid, "symbol": symbol,
            "company": "Infosys", "publication_ts": pub, "title": title,
            "body": body, "timestamp": pub}


def test_append_only_and_hash_stability():
    m1 = ST.ingest_batch("TEST", [_raw()])
    assert m1["records_valid"] == 1 and m1["status"] == "OK"
    rid = ST.record_id_for("NSE", ST.payload_hash("NSE", "INFY.NS", "Board Meeting Intimation",
                                                  "Body here", "2026-10-01T10:00:00+00:00"))
    assert ST.get_raw(rid)["title"] == "Board Meeting Intimation"
    # same payload twice -> same id, duplicate link, single row
    m2 = ST.ingest_batch("TEST", [_raw()])
    assert m2["records_duplicate"] == 1 and m2["records_valid"] == 0
    assert sqlite_conn().execute(
        "SELECT COUNT(*) FROM raw_events WHERE record_id=?", (rid,)).fetchone()[0] == 1
    assert any(l["relation"] == "duplicate_of" for l in ST.links_for(rid))
    # module exposes no update/delete primitives for raw rows
    assert not any(n.startswith(("update", "delete", "remove", "purge"))
                   for n in dir(ST) if not n.startswith("_"))


def test_amendment_preserved_and_linked():
    ST.ingest_batch("TEST", [_raw(sid="SRC-9", title="Financial Results")])
    m = ST.ingest_batch("TEST", [_raw(sid="SRC-9", title="Corrigendum: Financial Results")])
    assert m["records_valid"] == 1
    rows = sqlite_conn().execute(
        "SELECT record_id FROM raw_events WHERE source_id='SRC-9'").fetchall()
    assert len(rows) == 2
    links = ST.links_for(rows[1][0])
    assert any(l["relation"] == "amends" for l in links)


def test_bad_rows_counted_never_crash_batch():
    m = ST.ingest_batch("TEST", [_raw(), {"junk": True}, _raw(symbol="X")])
    assert m["records_valid"] == 1 and m["records_failed"] == 2
    assert m["status"] == "PARTIAL_FETCH"


def test_source_failure_logged_explicitly():
    ST.log_source_failure("NSE", "RATE_LIMITED", "TEST-throttled")
    with pytest.raises(ValueError):
        ST.log_source_failure("NSE", "NOPE", "TEST-")
    n = sqlite_conn().execute(
        "SELECT COUNT(*) FROM source_failures WHERE detail='TEST-throttled'").fetchone()[0]
    assert n == 1


def test_normalization_deterministic_and_versioned():
    assert TN.normalize_text("  Board   <b>Meeting</b> &amp; Results\n\n\nX") == \
        TN.normalize_text("board meeting & results\nx")
    assert TN.NORMALIZER_VERSION == "NORM_V1"
    ST.ingest_batch("TEST", [_raw(body="Body <i>HERE</i>")])
    rid = sqlite_conn().execute(
        "SELECT record_id FROM raw_events WHERE source_id='SRC-1'").fetchone()[0]
    norm = sqlite_conn().execute(
        "SELECT normalized_hash, normalizer_version FROM normalized_events"
        " WHERE record_id=?", (rid,)).fetchone()
    assert norm[1] == "NORM_V1" and len(norm[0]) == 16


def test_classification_append_only_and_gated():
    ST.ingest_batch("TEST", [_raw()])
    rid = sqlite_conn().execute(
        "SELECT record_id FROM raw_events WHERE source_id='SRC-1'").fetchone()[0]
    v1 = ST.append_classification(rid, {"event_type": "BOARD_MEETING", "severity": 0.6})
    v2 = ST.append_classification(rid, {"event_type": "EARNINGS", "severity": 0.8},
                                  classifier_version="classifier-v2")
    assert (v1["version"], v2["version"]) == (1, 2)
    assert len(ST.classifications_for(rid)) == 2  # v1 preserved, not overwritten
    with pytest.raises(ValueError):
        ST.append_classification(rid, {"event_type": "OTHER", "action": "BUY"})
    with pytest.raises(ValueError):
        ST.append_classification("EV-NSE-DEAD", {"event_type": "OTHER"})


def test_manifest_reproducible_fields():
    m = ST.ingest_batch("TEST", [_raw(), _raw(sid="SRC-2", title="Dividend")])
    for k in ("batch_id", "started_at", "ended_at", "records_received", "records_valid",
              "records_duplicate", "records_failed", "source_version",
              "ingestor_version", "batch_hash", "status"):
        assert k in m
    assert m["records_received"] == 2 and len(m["batch_hash"]) == 16
