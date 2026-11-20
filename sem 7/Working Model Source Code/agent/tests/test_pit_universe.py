"""PIT universe tests: synthetic CSVs only, zero network (prereg_pit_universe.md Gate)."""
import csv

import pytest

from app.data import pit_universe as PU

HEADER = ["index_id", "index_name", "symbol", "valid_from", "valid_to",
          "weightage", "source", "source_url", "notes"]


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)


def _row(sym, frm, to, src="press_release", idx="221"):
    return {"index_id": idx, "index_name": "Nifty 500", "symbol": sym,
            "valid_from": frm, "valid_to": to, "weightage": "",
            "source": src, "source_url": "", "notes": ""}


def test_boundary_inclusion(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("AAA", "2021-01-01", "2021-06-30")])
    syms, _ = PU.members_at("221", "2021-01-01", path=p, renames_path=str(tmp_path / "nope.json"))
    assert syms == ["AAA"]
    syms, _ = PU.members_at("221", "2021-06-30", path=p, renames_path=str(tmp_path / "nope.json"))
    assert syms == ["AAA"]
    syms, _ = PU.members_at("221", "2021-07-01", path=p, renames_path=str(tmp_path / "nope.json"))
    assert syms == []
    assert PU.to_ns_tickers(syms) == []


def test_open_ended_spell_is_member(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("BBB", "2020-01-01", "")])
    syms, _ = PU.members_at("221", "2026-05-05", path=p, renames_path=str(tmp_path / "nope.json"))
    assert syms == ["BBB"]


def test_strict_filters_weak_sources_with_disclosure(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("CCC", "2020-01-01", "", src="press_release"),
               _row("DDD", "2020-01-01", "", src="snapshot_floor")])
    strict, meta = PU.members_at("221", "2022-01-01", strict=True, path=p,
                                 renames_path=str(tmp_path / "nope.json"))
    assert strict == ["CCC"] and meta["weak_rows_included"] == 0
    loose, meta2 = PU.members_at("221", "2022-01-01", strict=False, path=p,
                                 renames_path=str(tmp_path / "nope.json"))
    assert loose == ["CCC", "DDD"] and meta2["weak_rows_included"] == 1


def _renames_file(tmp_path, entries):
    import json
    rp = str(tmp_path / "ren.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"renames": entries}, f)
    return rp


def test_renames_applied_before_suffix(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("OLDCO", "2020-01-01", "")])
    rp = _renames_file(tmp_path, [{"old": "OLDCO", "new": "NEWCO", "effective_date": "2021-06-01"}])
    syms, _ = PU.members_at("221", "2022-01-01", path=p, renames_path=rp)
    assert syms == ["NEWCO"]
    assert PU.to_ns_tickers(syms) == ["NEWCO.NS"]


def test_rename_not_yet_effective_keeps_old(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("OLDCO", "2020-01-01", "")])
    rp = _renames_file(tmp_path, [{"old": "OLDCO", "new": "NEWCO", "effective_date": "2021-06-01"}])
    syms, _ = PU.members_at("221", "2021-01-01", path=p, renames_path=rp)
    assert syms == ["OLDCO"]  # rename not yet effective at as-of date


def test_start_date_excludes_future_joiners(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("EARLY", "2019-01-01", "2026-01-01"),
               _row("LATE", "2023-06-01", "")])
    syms, meta = PU.start_date_universe("221", "2021-01-01", path=p,
                                        renames_path=str(tmp_path / "nope.json"))
    assert syms == ["EARLY.NS"]  # LATE not yet a member at window start
    assert "CC BY" in meta["attribution"] and meta["index_id"] == "221"


def test_missing_file_raises_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        PU.members_at("221", "2021-01-01", path=str(tmp_path / "absent.csv"))


def test_other_index_ignored(tmp_path):
    p = str(tmp_path / "m.csv")
    _write(p, [_row("AAA", "2020-01-01", "", idx="217"),
               _row("BBB", "2020-01-01", "", idx="221")])
    syms, _ = PU.members_at("221", "2022-01-01", path=p, renames_path=str(tmp_path / "nope.json"))
    assert syms == ["BBB"]
