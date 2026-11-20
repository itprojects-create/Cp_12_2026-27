"""W1.1 PIT warehouse tests — hermetic fixtures only, no network, no real archives.

Every fixture builds tiny synthetic source files in a tmp dir and ingests them
through the same code path used for the real archives. Required inventory:
``test_pit_unavailable_at_cutoff_rejected``, ``test_asof_index_membership_no_
survivorship``, ``test_delisted_symbol_and_corporate_action_handling``.
"""
from __future__ import annotations

import gzip
import json
import sqlite3

import pytest

from quantplus_intelligence.research_v3 import warehouse as W


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------

BHAV_HEADER = "date,symbol,series,open,high,low,close,last,prevclose,volume,value,trades,isin"


def _bhav_row(session, symbol, series="EQ", o="100", h="105", l="99", c="102",
              prev="98", vol="1000", val="102000", trades="10", isin="INE000TEST01"):
    return f"{session},{symbol},{series},{o},{h},{l},{c},{c},{prev},{vol},{val},{trades},{isin}"


@pytest.fixture()
def db(tmp_path):
    return W.connect(str(tmp_path / "wh.sqlite3"))


def _write_bhavcopy(tmp_path, rows):
    path = tmp_path / "bhav.csv.gz"
    body = "\n".join([BHAV_HEADER, *rows]) + "\n"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(body)
    return str(path)


@pytest.fixture()
def bhav_path(tmp_path):
    rows = [
        # ABC: listed from 2024-01-02; 5 sessions; goes away after 2024-01-09
        _bhav_row("2024-01-02", "ABC", o="100", h="104", l="99", c="103", prev="98"),
        _bhav_row("2024-01-03", "ABC", o="103", h="110", l="102", c="108", prev="103"),
        _bhav_row("2024-01-04", "ABC", o="108", h="109", l="95", c="96", prev="108"),
        _bhav_row("2024-01-05", "ABC", o="96", h="99", l="94", c="97", prev="96"),
        _bhav_row("2024-01-09", "ABC", o="97", h="101", l="96", c="99", prev="97"),
        # DELISTED: nifty50 member until 2023-06-30; bars exist only inside the
        # membership spell (survivorship fixture: decision inside the spell)
        _bhav_row("2023-06-25", "DELISTED", o="50", h="52", l="49", c="51", prev="50",
                  isin="INE000DELIST"),
        _bhav_row("2023-06-26", "DELISTED", o="51", h="53", l="50", c="52", prev="51",
                  isin="INE000DELIST"),
        # XYZ: price 100 exactly on 2024-01-02 then 200 (2:1 split shape for actions)
        _bhav_row("2024-01-02", "XYZ", o="100", h="100", l="100", c="100", prev="100"),
        _bhav_row("2024-01-03", "XYZ", o="50", h="52", l="49", c="51", prev="50"),
        _bhav_row("2024-01-04", "XYZ", o="51", h="55", l="50", c="54", prev="51"),
    ]
    return _write_bhavcopy(tmp_path, rows)


# ---------------------------------------------------------------------------
# ingestion + PIT joins
# ---------------------------------------------------------------------------


class TestIngestion:
    def test_ingest_and_paise_exactness(self, db, bhav_path):
        meta = W.ingest_bhavcopy(db, bhav_path)
        assert meta["rows_ingested"] == 10
        n = db.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        assert n == 10
        # 103.00 rupees -> 10300 paise exactly; value 102000 rupees -> 10200000 paise
        row = db.execute("SELECT close_paise, value_paise FROM daily_bars "
                         "WHERE symbol='ABC' AND session='2024-01-02'").fetchone()
        assert row == (10300, 10_200_000)

    def test_reingest_is_append_only_no_duplicates(self, db, bhav_path):
        W.ingest_bhavcopy(db, bhav_path)
        before = db.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        meta2 = W.ingest_bhavcopy(db, bhav_path)
        after = db.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        assert before == after == 10
        assert meta2["rows_ignored_duplicates"] == 10
        # source hash recorded exactly once
        runs = db.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
        assert runs == 1

    def test_missing_archive_raises_no_synth(self, db, tmp_path):
        with pytest.raises(FileNotFoundError):
            W.ingest_bhavcopy(db, str(tmp_path / "nope.csv.gz"))

    def test_unrepresentable_price_rejected(self, db, tmp_path):
        rows = [_bhav_row("2024-01-02", "ABC", c="10.225")]  # 3 decimals: not exact paise
        path = _write_bhavcopy(tmp_path, rows)
        with pytest.raises(ValueError, match="exact paise"):
            W.ingest_bhavcopy(db, path)


class TestPitAvailability:
    def test_pit_unavailable_at_cutoff_rejected(self, db, bhav_path):
        """Session 2024-01-03's bar is available 2024-01-04T00:15 IST, not before."""
        W.ingest_bhavcopy(db, bhav_path)
        res = W.bars_asof(db, "ABC", "2024-01-03T00:00:00+05:30", end_session="2024-01-03")
        assert res.status == "NOT_AVAILABLE_AT_CUTOFF"
        assert res.rows == ()
        assert res.meta["bars_known_at_source"] == 5  # data exists, just not available yet

    def test_available_next_local_day_plus_delay(self, db, bhav_path):
        W.ingest_bhavcopy(db, bhav_path)
        res = W.bars_asof(db, "ABC", "2024-01-04T00:15:00+05:30", end_session="2024-01-03")
        assert res.status == "OK"
        assert res.rows[-1][0] == "2024-01-03"  # previous session now visible
        avail = db.execute("SELECT available_at FROM daily_bars WHERE symbol='ABC' "
                           "AND session='2024-01-03'").fetchone()[0]
        assert avail == "2024-01-04T00:15:00+05:30"

    def test_unknown_symbol_typed_miss(self, db, bhav_path):
        W.ingest_bhavcopy(db, bhav_path)
        res = W.bars_asof(db, "GHOST", "2026-01-01T00:00:00+05:30")
        assert res.status == "UNKNOWN_SYMBOL" and res.rows == ()

    def test_no_same_session_lookahead_even_at_close(self, db, bhav_path):
        """A decision at 15:30 of the session itself must NOT see that session's bar."""
        W.ingest_bhavcopy(db, bhav_path)
        res = W.bars_asof(db, "ABC", "2024-01-04T15:30:00+05:30", end_session="2024-01-04")
        sessions_seen = [r[0] for r in res.rows]
        assert "2024-01-04" not in sessions_seen


# ---------------------------------------------------------------------------
# membership
# ---------------------------------------------------------------------------


def _write_membership(tmp_path, spells):
    path = tmp_path / "mem.csv"
    lines = ["index_id,index_name,symbol,valid_from,valid_to,weightage,source,source_url,notes"]
    for idx, sym, frm, to, src in spells:
        lines.append(f"{idx},Nifty 50,{sym},{frm},{to},,{src},x,")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _write_renames(tmp_path, entries=None):
    entries = entries or [{"old": "STAYER", "new": "STAYERNEW", "effective_date": "2024-05-01"}]
    ren = tmp_path / "ren.json"
    ren.write_text(json.dumps({"renames": entries}), encoding="utf-8")
    return str(ren)


@pytest.fixture()
def mem_path(tmp_path):
    return _write_membership(tmp_path, [
        # DELISTED was a nifty50 member 2020-2023 then removed (survivorship check)
        ("217", "DELISTED", "2020-01-01", "2023-06-30", "press_release"),
        # STAYER member throughout (with a *dated* strict row so strict mode works)
        ("217", "STAYER", "2020-01-01", "", "press_release"),
        # JOINER joins 2024-07-01: must NOT appear at 2024-01-01 decisions
        ("217", "JOINER", "2024-07-01", "", "press_release"),
        # snapshot_floor upper-bound spell for LATE (weak source)
        ("217", "LATE", "2020-01-01", "", "snapshot_floor"),
    ])


class TestMembership:
    def test_asof_membership_and_attribution(self, db, mem_path):
        W.ingest_membership(db, mem_path)
        res = W.members_at(db, "nifty50", "2024-01-01")
        assert res.status == "PARTIAL"  # snapshot_floor row included -> disclosed
        # DELISTED's spell ended 2023-06-30 -> correctly NOT a member on 2024-01-01
        assert res.rows == ("LATE", "STAYER")  # JOINER not yet a member
        assert "CC BY 4.0" in res.meta["attribution"]

    def test_asof_index_membership_no_survivorship(self, db, mem_path, bhav_path):
        """A member removed in 2023 is still a member at 2022 decisions, and its
        2022 bars remain usable — no current-members substitution anywhere."""
        W.ingest_membership(db, mem_path)
        W.ingest_bhavcopy(db, bhav_path)
        # decision INSIDE the membership spell (2020-01-01..2023-06-30):
        res = W.members_at(db, "nifty50", "2023-06-27")
        assert "DELISTED" in res.rows
        # panel join keeps the delisted name's available bars (through 06-26)
        panel = W.panel_asof(db, "nifty50", "2023-06-27T23:59:59+05:30")
        by_sym = {r["symbol"]: r for r in panel.rows}
        assert "DELISTED" in by_sym
        # ...with a bar that was actually available by the decision date
        assert "close_paise" in by_sym["DELISTED"]
        # after the spell ends the member disappears from as-of membership
        res2 = W.members_at(db, "nifty50", "2023-07-01")
        assert "DELISTED" not in res2.rows

    def test_joiner_not_backdated(self, db, mem_path):
        W.ingest_membership(db, mem_path)
        res = W.members_at(db, "nifty50", "2024-01-01")
        assert "JOINER" not in res.rows
        res2 = W.members_at(db, "nifty50", "2024-07-01")
        assert "JOINER" in res2.rows

    def test_strict_mode_excludes_weak_rows_and_discloses(self, db, mem_path):
        W.ingest_membership(db, mem_path)
        res = W.members_at(db, "nifty50", "2024-01-01", strict=True)
        assert res.rows == ("STAYER",)  # LATE excluded (weak); DELISTED spell ended 2023-06-30
        assert res.status == "VERIFIED"

    def test_unknown_universe_and_predates_history(self, db, mem_path):
        W.ingest_membership(db, mem_path)
        assert W.members_at(db, "nifty6000", "2024-01-01").status == "UNKNOWN"
        assert W.members_at(db, "nifty50", "2019-01-01").status == "UNKNOWN"

    def test_rename_canonicalisation_date_aware(self, db, mem_path, tmp_path):
        ren = _write_renames(tmp_path)
        W.ingest_membership(db, mem_path, renames_path=ren)
        assert W.canonical_symbol(db, "STAYER", "2024-04-30") == "STAYER"
        assert W.canonical_symbol(db, "STAYER", "2024-05-01") == "STAYERNEW"
        # bars follow the INSTRUMENT: the canonical symbol's alias set always
        # includes pre-rename raw names, regardless of decision date
        # (date gating lives only in membership naming — canonical_symbol above)
        assert W.alias_symbols_at(db, "STAYERNEW", "2024-04-30") == ["STAYERNEW", "STAYER"]
        assert W.alias_symbols_at(db, "STAYERNEW", "2024-05-01") == ["STAYERNEW", "STAYER"]

    def test_alias_lookup_finds_pre_rename_bars(self, db, mem_path, tmp_path):
        """Bars follow the INSTRUMENT through a rename: a bar ingested under the
        OLD symbol answers canonical-NEW-symbol queries at ANY decision date —
        identity, not date-gated naming."""
        path = tmp_path / "alias_bhav.csv.gz"
        rows = [_bhav_row("2024-05-02", "STAYER", o="100", h="104", l="99", c="103",
                          prev="98", isin="INE000STAY01")]
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write("\n".join([BHAV_HEADER, *rows]) + "\n")
        W.ingest_membership(db, mem_path, renames_path=_write_renames(tmp_path))
        W.ingest_bhavcopy(db, str(path))
        res_old = W.bars_asof(db, "STAYER", "2024-05-03T00:15:00+05:30")
        assert res_old.status == "OK"  # queried under the raw old name directly
        res_new_before = W.bars_asof(db, "STAYERNEW", "2024-05-03T00:15:00+05:30")
        assert res_new_before.status == "OK"  # alias set is unconditional
        assert res_new_before.meta["aliases"] == ["STAYERNEW", "STAYER"]
        assert res_new_before.rows == res_old.rows  # same instrument, same bar
        res_new_after = W.bars_asof(db, "STAYERNEW", "2024-06-01T00:15:00+05:30")
        assert res_new_after.status == "OK"  # and it stays findable after the rename

    def test_undated_and_placeholder_renames_fail_closed(self, db, mem_path, tmp_path):
        """Undated renames (source ``effective_date: null``) and placeholder
        dates (``2026-01-XX``) prove instrument IDENTITY but never change
        display naming and never mirror a verified corporate action."""
        entries = [
            {"old": "STAYER", "new": "STAYERNEW", "effective_date": "2024-05-01"},
            {"old": "RNAM", "new": "NAM-INDIA", "effective_date": None},    # undated
            {"old": "LTIM", "new": "LTM", "effective_date": "2026-01-XX"},  # placeholder
            {"old": "MFSL", "new": "MFSL", "effective_date": None},         # no-op
        ]
        meta = W.ingest_membership(
            db, mem_path, renames_path=_write_renames(tmp_path, entries))
        assert meta["renames_undated"] == 2
        assert meta["renames_invalid_date_strings"] == 1
        # identity: alias joins are unconditional and contain no duplicates
        assert W.alias_symbols_at(db, "NAM-INDIA") == ["NAM-INDIA", "RNAM"]
        assert W.alias_symbols_at(db, "MFSL") == ["MFSL"]  # no-op not duplicated
        # display naming fails closed: nothing retroactive, nothing speculative
        assert W.canonical_symbol(db, "RNAM", "2030-01-01") == "RNAM"
        assert W.canonical_symbol(db, "LTIM", "2026-02-01") == "LTIM"
        # dated rename still applies on/after its verified date
        assert W.canonical_symbol(db, "STAYER", "2024-05-01") == "STAYERNEW"
        # only the VERIFIED-dated rename mirrors a corporate action
        n_actions = db.execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE new_symbol IN "
            "('NAM-INDIA','LTM') AND source='nse_symbol_renames.json'").fetchone()[0]
        assert n_actions == 0
        n_stayer = db.execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE new_symbol='STAYERNEW' "
            "AND source='nse_symbol_renames.json'").fetchone()[0]
        assert n_stayer == 1


# ---------------------------------------------------------------------------
# corporate actions + lifecycle
# ---------------------------------------------------------------------------


class TestCorporateActions:
    def test_delisted_symbol_and_corporate_action_handling(self, db, mem_path, bhav_path, tmp_path):
        """Delisted name keeps its panel presence; verified rename action applies;
        unregistered actions abstain as UNKNOWN (never imputed)."""
        W.ingest_membership(db, mem_path, renames_path=str(_write_renames(tmp_path)))
        W.ingest_bhavcopy(db, bhav_path)
        life = W.instrument_lifecycle(db, "DELISTED")
        assert life["first_session"] == "2023-06-25" and life["last_session"] == "2023-06-26"
        # rename corporate action was registered by ingest_membership (verified)
        f, status = W.adjustment_factor(db, "STAYERNEW", "2024-06-01")
        assert status == "VERIFIED" and f == 1.0
        # a symbol with NO registered actions abstains as UNKNOWN
        f2, status2 = W.adjustment_factor(db, "ABC", "2024-01-04")
        assert (f2, status2) == (1.0, "UNKNOWN")
        # registered split: factor applies only from its effective date
        db.execute("INSERT OR IGNORE INTO corporate_actions VALUES "
                   "('XYZ','split','2024-01-03',0.5,NULL,NULL,'test',1)")
        db.commit()
        assert W.adjustment_factor(db, "XYZ", "2024-01-02") == (1.0, "VERIFIED")
        f3, s3 = W.adjustment_factor(db, "XYZ", "2024-01-03")
        assert s3 == "VERIFIED" and abs(f3 - 0.5) < 1e-12


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------


def _write_tri(tmp_path, rows):
    path = tmp_path / "tri.csv"
    lines = ["date,index_name,total_returns_index"]
    for d, v in rows:
        lines.append(f"{d},Nifty 50,{v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestBenchmark:
    def test_t_plus_1_join_and_reverse_chrono_input(self, db, tmp_path):
        # deliberately reverse-chronological input, with duplicate last date
        path = _write_tri(tmp_path, [("03 Jan 2024", 101.0), ("02 Jan 2024", 100.0),
                                     ("02 Jan 2024", 100.5)])
        W.ingest_nifty50_tri(db, path)
        # T+1 join: uncovered before the first ingested point -> loud error
        with pytest.raises(ValueError, match="uncovered"):
            W.benchmark_total_return(db, "NIFTY50_TRI", "2023-12-31", "2024-01-04")
        # start resolves to value at-or-before 2024-01-02 (dedupe keeps last: 100.5)
        r = W.benchmark_total_return(db, "NIFTY50_TRI", "2024-01-02", "2024-01-04")
        assert r["start_session"] == "2024-01-02" and r["end_session"] == "2024-01-03"
        assert abs(r["total_return"] - (101.0 / 100.5 - 1)) < 1e-9
        assert "price index is a separate series" in r["basis"]

    def test_missing_tri_file_raises(self, db, tmp_path):
        with pytest.raises(FileNotFoundError):
            W.ingest_nifty50_tri(db, str(tmp_path / "no.csv"))


# ---------------------------------------------------------------------------
# fee schedules + coverage
# ---------------------------------------------------------------------------


class TestFeeSchedulesAndCoverage:
    def test_fee_schedule_mirror_records_boundary(self, db):
        W.ingest_fee_schedules(db)
        rows = db.execute("SELECT schedule_id, effective_from, kind FROM fee_schedules "
                          "ORDER BY kind, effective_from").fetchall()
        kinds = {r[2] for r in rows}
        assert any(k.startswith("broker_component:") for k in kinds)
        assert any(k == "statutory_exchange" for k in kinds)

    def test_coverage_report_lists_named_gaps(self, db, bhav_path, mem_path, tmp_path):
        W.ingest_bhavcopy(db, bhav_path)
        W.ingest_membership(db, mem_path)
        W.ingest_nifty50_tri(db, _write_tri(tmp_path, [("02 Jan 2024", 100.0)]))
        rep = W.coverage_report(db)
        assert rep["distinct_symbols"] == 3
        assert rep["sessions_per_year"] == {"2023": 2, "2024": 5}
        assert rep["known_gaps"]["2024-01-01_to_2024-06-20"]["state"].startswith("NOT_APPLICABLE")
        assert rep["known_gaps"]["2026-09-18_onward"]["status"] == "MISSING_SPAN"
        assert "CC BY 4.0" in rep["membership_spells"]["attribution"]
        assert rep["rights"]["membership"].startswith("CC BY 4.0")

    def test_gap_state_flags_missing_span_for_real_source(self, db, tmp_path):
        """With the real bhavcopy run recorded and no H1-2024 sessions, the named
        gap flips to MISSING_SPAN (mechanism test, not a real-data run)."""
        path = _write_bhavcopy(tmp_path, [_bhav_row("2024-07-01", "ABC")])
        # ingest then relabel the run as the real source (path + id) to exercise
        # the gap mechanism without touching the real archive
        W.ingest_bhavcopy(db, path)
        db.execute("UPDATE ingestion_runs SET source_id='nse_eod_bhavcopy_2015_2026_full', "
                   "source_path=?", (W.BHAVCOPY_PATH,))
        db.commit()
        rep = W.coverage_report(db)
        gap = rep["known_gaps"]["2024-01-01_to_2024-06-20"]
        assert gap["state"] == "MISSING_SPAN" and gap["sessions_ingested"] == 0

    def test_sessions_and_next_session_after(self, db, bhav_path):
        W.ingest_bhavcopy(db, bhav_path)
        assert W.sessions(db) == ["2023-06-25", "2023-06-26", "2024-01-02", "2024-01-03",
                                  "2024-01-04", "2024-01-05", "2024-01-09"]
        assert W.next_session_after(db, "2024-01-05") == "2024-01-09"
        assert W.next_session_after(db, "2024-01-09") is None  # edge: explicit None
