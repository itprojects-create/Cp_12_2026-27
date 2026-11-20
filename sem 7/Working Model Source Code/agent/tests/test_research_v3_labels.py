"""W1.2 executable-label + fee-edge tests (hermetic fixtures, integer paise).

Required inventory covered here: ``test_next_executable_entry_prevents_same_
close_lookahead``, ``test_fee_paissa_reconciliation_by_size_side_and_date``,
plus NO_FILL/extension and schedule-boundary semantics.
"""
from __future__ import annotations

import gzip

import pytest

from quantplus_intelligence.research_v3 import economics as E
from quantplus_intelligence.research_v3 import labels as L
from quantplus_intelligence.research_v3 import warehouse as W

BHAV_HEADER = "date,symbol,series,open,high,low,close,last,prevclose,volume,value,trades,isin"


def _row(session, symbol, o, h, l, c, prev, vol="100000", val="0", trades="500",
         isin="INE000TEST01", series="EQ"):
    return f"{session},{symbol},{series},{o},{h},{l},{c},{c},{prev},{vol},{val},{trades},{isin}"


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "bhav.csv.gz"
    rows = [
        # 9 consecutive observed sessions for ABC in March 2026 (inside the
        # verified fee-schedule window); weekend skip kept realistic
        _row("2026-03-02", "ABC", "100", "104", "99", "103", "98"),
        _row("2026-03-03", "ABC", "103", "110", "102", "108", "103"),
        _row("2026-03-04", "ABC", "108", "109", "95", "96", "108"),
        _row("2026-03-05", "ABC", "96", "99", "94", "97", "96"),
        _row("2026-03-06", "ABC", "97", "101", "96", "99", "97"),
        _row("2026-03-09", "ABC", "99", "106", "98", "105", "99"),
        _row("2026-03-10", "ABC", "105", "107", "104", "106", "105"),
        _row("2026-03-11", "ABC", "106", "112", "105", "111", "106"),
        _row("2026-03-12", "ABC", "111", "115", "110", "114", "111"),
        # HALT: no bars for ZXZ on 2026-03-10..11 (conservative-exit fixture)
        _row("2026-03-06", "ZXZ", "50", "51", "49", "50", "49", isin="INE000ZXZ001"),
        _row("2026-03-09", "ZXZ", "50", "51", "49", "50", "50", isin="INE000ZXZ001"),
        _row("2026-03-12", "ZXZ", "55", "56", "54", "55", "55", isin="INE000ZXZ001"),
    ]
    body = "\n".join([BHAV_HEADER, *rows]) + "\n"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(body)
    conn = W.connect(str(tmp_path / "wh.sqlite3"))
    W.ingest_bhavcopy(conn, str(path))
    tri = tmp_path / "tri.csv"
    tri.write_text("date,index_name,total_returns_index\n"
                   "01 Mar 2026,Nifty 50,100.0\n"
                   "31 Mar 2026,Nifty 50,103.0\n", encoding="utf-8")
    W.ingest_nifty50_tri(conn, str(tri))
    return conn


class TestExecutableEntry:
    def test_next_executable_entry_prevents_same_close_lookahead(self, db):
        """A decision that knows the 2026-03-05 close (available 03-06T00:15)
        fills at the next tradable observation — the 03-06 session open,
        never at the already-known close 97.00."""
        label = L.executable_label(db, "ABC", "2026-03-06T00:15:00+05:30", 2)
        assert label["status"] == "OK"
        assert label["decision_baseline_session"] == "2026-03-05"
        assert label["decision_baseline_close_paise"] == 9700
        assert label["entry"]["session"] == "2026-03-06"
        assert label["entry"]["ref_price_paise"] == 9700  # 03-06 open = 97.00
        assert label["entry"]["ref_kind"] == "OPEN"
        assert label["next_eligible_entry_time"] == "2026-03-07T00:15:00+05:30"
        # exit = 2 observed sessions after entry -> 2026-03-10 close 106.00
        assert label["exit"]["session"] == "2026-03-10"
        assert label["exit"]["ref_price_paise"] == 10600
        assert label["exit"]["extended"] is False
        assert label["charges_status"] == "OK"
        # 9700 -> 10600 up-move with positive costs still nets positive cash
        assert label["accounting"]["v3_trade_cash_pnl_paise"] > 0

    def test_net_cash_exact_on_fixture(self, db):
        """₹1,00,000 notional at open Rs 97.00 -> 1030 shares; verify paise."""
        label = L.executable_label(db, "ABC", "2026-03-06T00:15:00+05:30", 2)
        acct = label["accounting"]
        assert acct["quantity"] == 1030  # 10_000_000 paise // 9700 paise
        expected = acct["sell_turnover_paise"] - acct["buy_turnover_paise"] - acct["charges_total_paise"]
        assert acct["v3_trade_cash_pnl_paise"] == expected
        assert acct["buy_turnover_paise"] == 1030 * 9700

    def test_decision_inside_session_uses_prior_close_baseline(self, db):
        """A mid-session decision sees only strictly-earlier-available bars."""
        label = L.executable_label(db, "ABC", "2026-03-05T12:00:00+05:30", 2)
        assert label["decision_baseline_session"] == "2026-03-04"  # 03-05 bar not yet available
        assert label["entry"]["session"] == "2026-03-05"  # first tradable observation AFTER decision
        assert label["entry"]["ref_price_paise"] == 9600  # 03-05 open

    def test_no_fill_when_history_ends_before_horizon(self, db):
        label = L.executable_label(db, "ABC", "2026-03-10T16:00:00+05:30", 5)
        assert label["status"] == "NO_FILL"
        assert "history ends" in label["note"]

    def test_conservative_exit_extension_labelled(self, db):
        """ZXZ has no bars 03-10/11; entry 03-09, 2-session horizon targets
        03-11 (no bar) -> exit extends to 03-12, explicitly labelled."""
        label = L.executable_label(db, "ZXZ", "2026-03-09T00:15:00+05:30", 2)
        assert label["status"] == "OK"
        assert label["entry"]["session"] == "2026-03-09"
        assert label["exit"]["session"] == "2026-03-12"
        assert label["exit"]["extended"] is True  # labelled, never silent

    def test_open_exit_ref_rolls_execution_to_execution(self, db):
        """``exit_ref='OPEN'`` prices the exit at the target session's OPEN —
        the rolling-portfolio convention: the chain rolls from one rebalance
        execution price to the next with no skipped boundary move."""
        lab = L.executable_label(db, "ABC", "2026-03-06T00:15:00+05:30", 2,
                                 exit_ref="OPEN")
        assert lab["status"] == "OK"
        assert lab["entry"]["session"] == "2026-03-06"
        assert lab["entry"]["ref_price_paise"] == 9700
        assert lab["exit"]["session"] == "2026-03-10"
        assert lab["exit"]["ref_price_paise"] == 10500  # 03-10 OPEN, not its close
        assert lab["exit"]["ref_kind"] == "OPEN"
        # halting name: the conservative extension uses the next available OPEN
        lab2 = L.executable_label(db, "ZXZ", "2026-03-09T00:15:00+05:30", 2,
                                  exit_ref="OPEN")
        assert lab2["exit"]["session"] == "2026-03-12"
        assert lab2["exit"]["ref_price_paise"] == 5500  # 03-12 open
        assert lab2["exit"]["extended"] is True
        with pytest.raises(ValueError):
            L.executable_label(db, "ABC", "2026-03-06T00:15:00+05:30", 2,
                               exit_ref="VWAP")

    def test_no_decision_baseline(self, db):
        label = L.executable_label(db, "ABC", "2026-03-02T00:00:00+05:30", 2)
        assert label["status"] == "NO_DECISION_BASELINE"

    def test_benchmark_relative_is_not_cash(self, db):
        label = L.executable_label(db, "ABC", "2026-03-05T16:00:00+05:30", 2)
        acct = label["accounting"]
        assert label["semantics"]["v3_benchmark_relative"].startswith("excess return")
        # cash P&L is exactly sale - cost - charges in paise
        expected = acct["sell_turnover_paise"] - acct["buy_turnover_paise"] - acct["charges_total_paise"]
        assert acct["v3_trade_cash_pnl_paise"] == expected
        # benchmark-relative number and cash P&L are different quantities
        assert label["v3_benchmark_relative"] != acct["v3_net_absolute"]


class TestFeePaiseReconciliation:
    def test_fee_paissa_reconciliation_by_size_side_and_date(self):
        """Size- and side-dependence reconciled paise-for-paise (W0 truth)."""
        # Rs 10,000 BUY at the 2026-03-01 schedule
        buy_10k = E.delivery_charges("BUY", 1_000_000, "2026-03-01T00:00:00+05:30")
        sell_10k = E.delivery_charges("SELL", 1_000_000, "2026-03-01T00:00:00+05:30")
        assert buy_10k["total_paise"] == 1188
        assert sell_10k["total_paise"] == 1038
        # Rs 1,00,000 both sides
        assert E.delivery_charges("BUY", 10_000_000, "2026-03-01T00:00:00+05:30")["total_paise"] == 11874
        assert E.delivery_charges("SELL", 10_000_000, "2026-03-01T00:00:00+05:30")["total_paise"] == 10374
        # FYERS component: min(0.3% x value, Rs 20) per executed order
        f_10k = E.delivery_charges("BUY", 1_000_000, "2026-03-01T00:00:00+05:30",
                                   broker="fyers_delivery_2026")
        f_1l = E.delivery_charges("BUY", 10_000_000, "2026-03-01T00:00:00+05:30",
                                  broker="fyers_delivery_2026")
        # 0.3% of Rs 10k = Rs 30 > Rs 20 cap; 0.3% of Rs 1L = Rs 300 > Rs 20 cap
        assert f_10k["total_paise"] == buy_10k["total_paise"] + 2000 + _gst_delta(f_10k, buy_10k)
        assert f_1l["total_paise"] == buy_1l_charges()["total_paise"] + 2000 + _gst_delta(f_1l, buy_1l_charges())

    def test_multi_execution_charges_each_order(self):
        """Two executed orders charge per-order brokerage twice (first_fill only)."""
        one = E.delivery_charges("BUY", 10_000_000, "2026-03-01T00:00:00+05:30",
                                 broker="fyers_delivery_2026")
        second = E.delivery_charges("BUY", 10_000_000, "2026-03-01T00:00:00+05:30",
                                    broker="fyers_delivery_2026", first_fill_of_order=False)
        # second fill: no brokerage, no DP; GST only on exchange+SEBI
        assert one["total_paise"] - second["total_paise"] == 2000 + _gst_delta(one, second)
        # statutory-only second fill reconciles with the book's zero-brokerage schedule
        assert second["total_paise"] == E.delivery_charges(
            "BUY", 10_000_000, "2026-03-01T00:00:00+05:30", broker="book_zero_brokerage")["total_paise"]

    def test_schedule_effective_date_boundary_fails_closed(self):
        """Before 2026-03-01 the statutory schedule is UNKNOWN -> fail closed."""
        with pytest.raises(ValueError, match=E.ScheduleUnavailable):
            E.delivery_charges("BUY", 1_000_000, "2026-02-28T00:00:00+05:30")
        with pytest.raises(ValueError, match=E.ScheduleUnavailable):
            E.delivery_charges("SELL", 1_000_000, "2025-12-31T00:00:00+05:30")

    def test_partial_fill_size_dependence(self):
        """Splitting one BUY into two fills re-rounds STT per fill (rupee each)."""
        whole = E.delivery_charges("BUY", 5_080_000, "2026-03-01T00:00:00+05:30")
        a = E.delivery_charges("BUY", 2_540_000, "2026-03-01T00:00:00+05:30")
        b = E.delivery_charges("BUY", 2_540_000, "2026-03-01T00:00:00+05:30")
        stt_whole = next(i["amount_paise"] for i in whole["items"] if i["code"] == "STT")
        stt_a = next(i["amount_paise"] for i in a["items"] if i["code"] == "STT")
        stt_b = next(i["amount_paise"] for i in b["items"] if i["code"] == "STT")
        # one Rs 50.80 fill rounds STT to Rs 51; two Rs 25.40 fills round to 25+25
        assert stt_whole == 5100 and (stt_a, stt_b) == (2500, 2500)
        assert stt_whole != stt_a + stt_b  # per-fill rupee rounding is material


def _gst_delta(charged, base):
    """GST difference caused by a larger brokerage base between two breakdowns."""
    def gst(d):
        return next(i["amount_paise"] for i in d["items"] if i["code"] == "GST")
    return gst(charged) - gst(base)


class TestScheduleBoundaryInLabels:
    def test_labels_before_fee_effective_keep_gross_only(self, tmp_path):
        """Bars before the schedule's effective date: gross metrics present,
        net metrics withheld (None) — never priced with a later schedule."""
        path = tmp_path / "old.csv.gz"
        rows = [
            _row("2024-01-02", "OLD", "100", "104", "99", "103", "98",
                 isin="INE000OLD001"),
            _row("2024-01-03", "OLD", "103", "110", "102", "108", "103",
                 isin="INE000OLD001"),
            _row("2024-01-04", "OLD", "108", "109", "95", "96", "108",
                 isin="INE000OLD001"),
            _row("2024-01-05", "OLD", "96", "99", "94", "97", "96",
                 isin="INE000OLD001"),
        ]
        body = "\n".join([BHAV_HEADER, *rows]) + "\n"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(body)
        conn = W.connect(str(tmp_path / "wh.sqlite3"))
        W.ingest_bhavcopy(conn, str(path))
        tri = tmp_path / "tri.csv"
        tri.write_text("date,index_name,total_returns_index\n"
                       "01 Jan 2024,Nifty 50,100.0\n"
                       "28 Feb 2024,Nifty 50,101.0\n", encoding="utf-8")
        W.ingest_nifty50_tri(conn, str(tri))
        # decision that knows the 2024-01-02 close (available 01-03T00:15)
        label = L.executable_label(conn, "OLD", "2024-01-03T00:15:00+05:30", 1)
        assert label["status"] == "OK"
        assert label["charges_status"] == "SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE"
        assert label["accounting"] is None
        assert label["v3_gross_absolute"] is not None
        assert label["v3_benchmark_relative"] is not None
        assert "withheld" in label["note"]


def buy_1l_charges():
    return E.delivery_charges("BUY", 10_000_000, "2026-03-01T00:00:00+05:30")
