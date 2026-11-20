"""P0 PIT membership tests (§7). Hermetic fixture CSVs — the real vendored file
is only read (never written) by one audit test."""
from __future__ import annotations

import csv

import pytest

from app.data import pit_membership as PM

HEADER = ["index_id", "index_name", "symbol", "valid_from", "valid_to",
          "weightage", "source", "source_url", "notes"]


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)


def _row(sym, frm, to="", src="press_release"):
    return ["217", "Nifty 50", sym, frm, to, "", src, "", ""]


@pytest.fixture()
def fix(tmp_path):
    p = str(tmp_path / "mem.csv")
    _write(p, [
        _row("ALWAYS", "2015-01-01", ""),
        _row("LATE", "2022-01-01", ""),
        _row("GONE", "2015-01-01", "2020-12-31"),
        _row("WEAK", "2015-01-01", "", src="snapshot_floor"),
    ])
    PM.clear_cache()
    yield p
    PM.clear_cache()


def _mem(path, date, strict=True):
    return PM.membership_at("nifty50", date, strict=strict, path=path)


def test_added_later_invisible_earlier(fix):
    assert "LATE.NS" not in _mem(fix, "2021-06-01")["members"]
    assert "LATE.NS" in _mem(fix, "2022-06-01")["members"]
    assert "ALWAYS.NS" in _mem(fix, "2021-06-01")["members"]


def test_removed_earlier_absent_later(fix):
    assert "GONE.NS" in _mem(fix, "2020-06-01")["members"]
    assert "GONE.NS" not in _mem(fix, "2021-06-01")["members"]


def test_future_announcement_cannot_leak_backward(tmp_path):
    p = str(tmp_path / "ann.csv")
    _write(p, [_row("EARLY", "2020-01-01", "")])
    PM.clear_cache()
    ivs, _ = PM._loaded(p, True)
    iv = [x for x in ivs if x.instrument_id == "EARLY.NS"][0]
    iv_late = iv.model_copy(update={"announcement_timestamp": "2025-01-01T00:00:00+00:00"})
    assert PM.is_visible(iv_late, "2021-01-01") is False  # effective but unknowable
    assert PM.is_visible(iv_late, "2025-06-01") is True
    assert PM.is_visible(iv, "2021-01-01") is True  # no announcement bound: proxy rule
    PM.clear_cache()


def test_overlapping_intervals_rejected(tmp_path):
    p = str(tmp_path / "ov.csv")
    _write(p, [_row("DUP", "2020-01-01", "2021-12-31"), _row("DUP", "2021-06-01", "")])
    PM.clear_cache()
    with pytest.raises(ValueError):
        PM._loaded(p, True)
    PM.clear_cache()


def test_cross_source_overlap_is_ambiguity_not_error(tmp_path):
    p = str(tmp_path / "amb.csv")
    _write(p, [_row("REJOIN", "2020-01-01", "2021-12-31"),
               _row("REJOIN", "2021-06-01", "", src="snapshot_floor")])
    PM.clear_cache()
    ivs, meta = PM._loaded(p, False)
    assert len(meta["ambiguous_overlaps"]) == 1
    s = PM.membership_at("nifty50", "2021-09-01", strict=False, path=p)
    assert "REJOIN.NS" in s["members"]  # overlap agrees on membership
    assert s["pit_status"] == "PARTIAL" and s["ambiguous_visible"] is True
    PM.clear_cache()


def test_malformed_intervals_rejected_with_counts(tmp_path):
    p = str(tmp_path / "bad.csv")
    _write(p, [_row("OK", "2020-01-01", ""),
               ["217", "Nifty 50", "NODATE", "", "", "", "press_release", "", ""],
               ["217", "Nifty 50", "BACKWARDS", "2021-01-01", "2020-01-01", "",
                "press_release", "", ""]])
    PM.clear_cache()
    ivs, meta = PM._loaded(p, True)
    assert meta["rejected"]["malformed"] == 2
    assert {x.instrument_id for x in ivs} == {"OK.NS"}
    PM.clear_cache()


def test_missing_intervals_return_unknown(fix):
    assert _mem(fix, "2026-10-01")["pit_status"] in ("VERIFIED", "PARTIAL")
    assert PM.membership_at("nope", "2026-10-01", path=fix)["pit_status"] == "UNKNOWN"
    assert PM.membership_at("nifty50", "1990-01-01", path=fix)["pit_status"] == "UNKNOWN"


def test_snapshot_deterministic_and_hash_stable(fix):
    a = _mem(fix, "2023-06-15")
    b = _mem(fix, "2023-06-15")
    assert a == b and a["membership_hash"] == b["membership_hash"]
    c = _mem(fix, "2023-06-16")  # same set, next day
    assert c["membership_hash"] == a["membership_hash"]
    assert set(a) >= {"members", "decision_timestamp", "membership_source_version",
                      "membership_hash", "coverage", "missing_records", "pit_status",
                      "strict"}


def test_weak_rows_partial_and_excluded_strict(fix):
    strict = _mem(fix, "2023-06-15", strict=True)
    loose = _mem(fix, "2023-06-15", strict=False)
    assert "WEAK.NS" not in strict["members"] and "WEAK.NS" in loose["members"]
    assert strict["pit_status"] == "PARTIAL"  # weak rows exist in source
    assert strict["missing_records"] > 0 and loose["missing_records"] == 0


def test_deliberate_leakage_fixture_caught(tmp_path):
    """A row whose effective_from is AFTER the decision date must never appear.
    If this test fails, the hard PIT rule is broken."""
    p = str(tmp_path / "leak.csv")
    _write(p, [_row("LEAK", "2022-01-01", "")])
    PM.clear_cache()
    got = PM.membership_at("nifty50", "2021-06-01", path=p)["members"]
    assert "LEAK.NS" not in got, "FUTURE-KNOWLEDGE LEAK: guard failed"
    PM.clear_cache()


def test_core_loop_exits_and_freezes():
    from app.core.trend_core_v4 import run_core_v4
    idx = [100 + i * 0.3 for i in range(120)]
    names = {"AAA.NS": [50 + j * 0.5 for j in range(120)],
             "BBB.NS": [50 + j * 0.4 for j in range(120)]}
    dates = [f"2024-01-{(i % 28) + 1:02d}" for i in range(120)]
    base = run_core_v4(idx, names)
    # all-member fn == legacy static behavior (byte-identical curve)
    fn_all = lambda d: {"members": {"AAA.NS", "BBB.NS"}, "pit_status": "VERIFIED",
                        "membership_hash": "h"}
    log: list = []
    same = run_core_v4(idx, names, dates=dates, membership_fn=fn_all, membership_log=log)
    assert same.eq_curve == base.eq_curve
    assert all(e["pit_status"] == "VERIFIED" for e in log) and len(log) == 120 // 5
    # BBB exits on 2024-01-15: never ranked/held after; UNKNOWN freezes (no-op here)
    def fn_mixed(d):
        if d >= "2024-01-20":
            return {"members": {"AAA.NS"}, "pit_status": "VERIFIED", "membership_hash": "h2"}
        return {"members": {"AAA.NS", "BBB.NS"}, "pit_status": "VERIFIED",
                "membership_hash": "h1"}
    mixed = run_core_v4(idx, names, dates=dates, membership_fn=fn_mixed)
    assert mixed.eq_curve != base.eq_curve  # membership had an effect (bias removed)
    frozen = run_core_v4(idx, names, dates=dates,
                         membership_fn=lambda d: {"members": set(),
                                                  "pit_status": "UNKNOWN",
                                                  "membership_hash": "u"})
    assert frozen.exposure == 0.0  # never entered: frozen from bar 0


def test_real_file_audit_read_only():
    PM.clear_cache()
    s = PM.membership_at("nifty50", "2026-10-01", strict=False)
    assert len(s["members"]) >= 40  # non-strict ≈ full index (Amendment-1 disclosure)
    assert s["pit_status"] in ("VERIFIED", "PARTIAL")
    assert len(s["membership_source_version"]) == 16
    PM.clear_cache()
