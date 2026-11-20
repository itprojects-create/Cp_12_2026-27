"""Announcement pipeline tests (Phase 8). Deterministic, zero tokens."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.events import blackout as BO
from app.events import classify as CL
from app.events import ingest as ING
from app.events import normalize as NORM
from app.events.schemas import Announcement, validate_extraction

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def test_normalize_validates_dedups_and_rejects():
    raw = [
        {"source": "NSE", "symbol": "RELIANCE-EQ", "title": "Board Meeting Intimation",
         "timestamp": "2026-10-08T10:00:00"},
        {"source": "NSE", "symbol": "RELIANCE-EQ", "title": "Board Meeting Intimation",
         "timestamp": "2026-10-08T10:00:00"},  # duplicate
        {"source": "BSE", "symbol": "INFY.NS", "title": "  ", "timestamp": "2026-10-08"},
        {"source": "SMS", "symbol": "X", "title": "hi", "timestamp": "2026-10-08"},
        {"source": "NSE", "symbol": "TCS.NS", "title": "Results", "timestamp": "not-a-date"},
        {"source": "NSE", "symbol": "TCS.NS", "title": "Future leak",
         "timestamp": "2026-10-11T10:00:00"},  # future vs NOW
    ]
    recs, rep = NORM.normalize(raw, now=NOW)
    assert rep["n_kept"] == 1 and recs[0]["symbol"] == "RELIANCE.NS"
    assert rep["rejected"] == {"bad_source": 1, "bad_symbol": 0, "bad_title": 1,
                               "bad_timestamp": 1, "future": 1, "duplicate": 1}


def test_rule_classification_and_ambiguity():
    assert CL.classify_rule("Board Meeting to consider Financial Results")["event_type"] in (
        "BOARD_MEETING", "EARNINGS")
    assert CL.classify_rule("Interim Dividend declared")["dividend_related"] is True
    assert CL.classify_rule("Merger scheme approved")["merger_related"] is True
    assert CL.classify_rule("Routine disclosure about office timings") is None


def test_extraction_gate_rejects_orders_and_bad_shapes():
    evil = {"event_type": "BOARD_MEETING", "severity": 0.5, "action": "BUY",
            "source_timestamp": "2026-10-08T10:00:00+00:00",
            "effective_timestamp": "2026-10-08T10:00:00+00:00"}
    with pytest.raises(ValueError):
        validate_extraction(evil)
    with pytest.raises(ValueError):
        validate_extraction({"event_type": "MOON", "severity": 0.5,
                             "source_timestamp": "2026-10-08T10:00:00+00:00",
                             "effective_timestamp": "2026-10-08T10:00:00+00:00"})
    with pytest.raises(ValueError):
        validate_extraction({"event_type": "OTHER", "severity": 0.5,
                             "source_timestamp": "2026-10-08T10:00:00+00:00",
                             "effective_timestamp": "2026-10-07T10:00:00+00:00"})
    ok = validate_extraction({"event_type": "DIVIDEND", "severity": 0.4})
    assert ok.event_type == "DIVIDEND"
    # identity smuggling is a schema violation, not a merge
    with pytest.raises(ValueError):
        validate_extraction({"event_type": "OTHER", "source": "X", "symbol": "Y"})


def test_to_announcement_merges_without_order_path():
    rec = {"source": "NSE", "symbol": "INFY.NS", "title": "Board Meeting",
           "source_timestamp": "2026-10-08T10:00:00+00:00",
           "effective_timestamp": "2026-10-08T10:00:00+00:00"}
    a = CL.to_announcement(rec, CL.classify_rule(rec["title"]))
    assert a.blackout_candidate is True and a.uncertain is False
    b = CL.to_announcement(rec, None, {"event_type": "OTHER", "severity": 0.2})
    assert b.uncertain is True
    # LLM fields can never override identity/timestamps (rejected at the gate)
    with pytest.raises(ValueError):
        CL.to_announcement(rec, None, {"event_type": "OTHER", "severity": 0.2,
                                       "source": "X", "symbol": "Y"})


def test_blackout_windowing_and_abstention():
    def ann(day, bc=True):
        return Announcement(source="NSE", symbol="INFY.NS", event_type="BOARD_MEETING",
                            severity=0.6, source_timestamp=f"2026-10-{day:02d}T10:00:00+00:00",
                            effective_timestamp=f"2026-10-{day:02d}T10:00:00+00:00",
                            blackout_candidate=bc)
    as_of = datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert BO.blackout_at("INFY.NS", as_of, [ann(9)], pre=2, post=1)[0] is True
    assert BO.blackout_at("INFY.NS", as_of, [ann(1)], pre=2, post=1)[0] is False
    assert BO.blackout_at("INFY.NS", as_of, [ann(9, bc=False)], pre=2, post=1)[0] is False
    flag, reason = BO.blackout_at("INFY.NS", as_of, [])
    assert flag is False and "unavailable" in reason
    assert BO.blackout_at("RELIANCE.NS", as_of, [ann(9)])[0] is False  # symbol-scoped
    with pytest.raises(ValueError):
        BO.blackout_at("X.NS", as_of, [], pre=9, post=1)
    assert BO.dsl_row_flag("INFY.NS", as_of, [ann(9)])["blackout"] is True


def test_ingest_never_raises_and_reads_local(tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert ING.fetch_nse_announcements("RELIANCE.NS", timeout_s=1) == []
    p = tmp_path / "feed.jsonl"
    p.write_text('{"source": "FILE", "symbol": "INFY", "title": "Board Meeting", '
                 '"timestamp": "2026-10-01"}\n', encoding="utf-8")
    rows = ING.read_local_feed(str(tmp_path / "*.jsonl"))
    assert len(rows) == 1 and rows[0]["title"] == "Board Meeting"
    assert ING.feed_files_present(str(tmp_path / "*.jsonl")) is True
    assert ING.feed_files_present(str(tmp_path / "none-*.jsonl")) is False
