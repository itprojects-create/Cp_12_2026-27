"""W2 Research Lab tests — hermetic, deterministic, fixture-backed.

The fixture is a synthetic but ACTION-COMPLETE micro-warehouse (not the real
ingested archive): integer-paise weekday bars for a handful of members, strict
press-release membership, an optional VERIFIED 2:1 split, an optional symbol
rename with alias continuity, an optional missing month, and an official-shape
TRI benchmark. Every test asserts typed behavior: availability gating,
discontinuity abstention, boundary-exit continuity, purge censoring,
NAV-from-ledger reconciliation, cash-consistent verified actions, blocked
economics for unverified actions and weak membership, negative-control
rejection, bounded sweeps, and the journal's seal/reveal discipline.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab import (
    JournalError, PitPanel, ResearchJournal, SpecError, StrategySpec,
    SignalSpec, ExecutionSpec, WindowSpec, challenge_finding, run_backtest,
    run_cost_scenarios, run_sweep)

IST = timezone(timedelta(hours=5, minutes=30))
SPLIT_DATE = "2026-07-15"
REN_DATE = "2026-10-15"
HOLE_MONTH = "2026-09"
WINDOWS = ("2026-03-01", "2026-12-31", "2027-01-01", "2027-03-31",
           "2027-04-01", "2027-06-30")

DRIFTS = {"AAA": 0.0010, "BBB": 0.0005, "CCC": 0.0002, "DDD": -0.0002,
          "EEE": -0.0005, "FFF": -0.0010, "GGG": 0.0004, "SPLIT": 0.0030,
          "REN": 0.0003}
BASES = {"AAA": 150_00, "BBB": 250_00, "CCC": 90_00, "DDD": 320_00,
         "EEE": 60_00, "FFF": 120_00, "GGG": 180_00, "SPLIT": 400_00,
         "REN": 210_00}


def _sessions() -> list[str]:
    out, d = [], date(2026, 3, 2)
    while d <= date(2027, 6, 30):
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


SESSIONS = _sessions()


def _make_fixture(path, *, weak=False, verified_split=True, hole=False,
                  rename=True):
    """Build the micro-warehouse. Returns (conn, truth).

    ``truth`` maps symbol -> {session: (open_paise, close_paise)} as generated
    (independent ground truth, not read back from the panel).
    """
    conn = W.connect(path)
    truth: dict[str, dict[str, tuple[int, int]]] = {}
    for sym, g in DRIFTS.items():
        series: dict[str, tuple[int, int]] = {}
        c_prev = BASES[sym]
        for s in SESSIONS:
            if hole and s[:7] == HOLE_MONTH:
                continue
            close = round(c_prev * (1 + g))
            if sym == "SPLIT" and s == SPLIT_DATE:
                close = round(close * 0.5)     # single 2:1 halving
            open_ = round(c_prev * 0.5) if (sym == "SPLIT" and s == SPLIT_DATE) \
                else c_prev
            bar_sym = "REN2" if (sym == "REN" and rename and s >= REN_DATE) else sym
            avail = (datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=IST)
                     + timedelta(days=1, minutes=15)).isoformat()
            conn.execute(
                "INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s, bar_sym, "EQ", "ISIN" + sym, open_, max(open_, close),
                 min(open_, close), close, c_prev, 1000, 100000, 10,
                 "fixture", "2026-01-01", avail, "fixture raw", "FIXTURE"))
            series[s] = (open_, close)
            c_prev = close
        truth[sym] = series

    members = list(DRIFTS)
    if not rename:
        members.remove("REN2")
    for sym in members:
        weak_row = weak and sym == "GGG"
        conn.execute(
            "INSERT INTO membership_spells VALUES (?,?,?,?,?,?,?,?,?)",
            ("999", "nifty50", sym, "2026-01-01", None,
             "snapshot_floor" if weak_row else "press_release",
             0 if weak_row else 1, "fixture", "fixture attribution (test)"))
    if rename:
        conn.execute("INSERT INTO symbol_renames VALUES "
                     "('REN','REN2','2026-10-15','fixture')")
        conn.execute("INSERT INTO corporate_actions VALUES "
                     "('REN2','symbol_change','2026-10-15',1.0,'REN','REN2',"
                     "'fixture',1)")
    if verified_split:
        # price-ratio factor convention: a 2:1 split carries factor 0.5 so that
        # sell_eff = sell_raw x cum_entry/cum_exit = 2 x post-split price
        conn.execute("INSERT INTO corporate_actions VALUES "
                     "('SPLIT','split','2026-07-15',0.5,NULL,NULL,'fixture',1)")
    for s, v in (("2026-03-02", 1000.0), ("2026-06-30", 1020.0),
                 ("2026-12-31", 1060.0), ("2027-03-31", 1080.0),
                 ("2027-06-25", 1120.0)):
        conn.execute("INSERT INTO benchmark_bars VALUES "
                     "('NIFTY50_TRI',?,?,'fixture','2026-01-01',"
                     "'official fixture TRI')", (s, v))
    conn.commit()
    return conn, truth


def _spec(windows=WINDOWS, *, family="cross_sectional_momentum", lookback=21,
          top_k=3, bps=10, high_window=252, control=False, spec_id="lab.h1",
          capital=10_000_000):
    return StrategySpec(
        spec_id=spec_id, version=1,
        hypothesis=("negative control: demonstrates the challenger's audit "
                    if control else "fixture momentum hypothesis (test)"),
        signal=SignalSpec(family, lookback_sessions=lookback, top_k=top_k,
                          high_window_sessions=high_window),
        execution=ExecutionSpec(capital_paise=capital, slippage_bps=bps),
        windows=WindowSpec(*windows),
        declared_negative_control=control)


# ---------------------------------------------------------------------------
# spec contracts
# ---------------------------------------------------------------------------

def test_spec_rejects_capital_directives():
    with pytest.raises(SpecError):
        StrategySpec("x", 1, hypothesis="buy RELIANCE at market open")
    with pytest.raises(SpecError):
        StrategySpec("x", 1, hypothesis="hold", notes="weights: [0.5,0.5]")
    with pytest.raises(SpecError):
        StrategySpec("x", 1, hypothesis="target price 100 on breakout")


def test_spec_rejects_undeclared_negative_control():
    with pytest.raises(SpecError):
        StrategySpec("x", 1, hypothesis="leak probe",
                     signal=SignalSpec("leak_control"))
    ok = StrategySpec("x", 1, hypothesis="declared leak probe",
                      signal=SignalSpec("leak_control"), declared_negative_control=True)
    assert ok.declared_negative_control


def test_spec_fingerprint_and_preregistration():
    a = _spec(spec_id="same")
    b = _spec(spec_id="same")
    assert a.fingerprint() == b.fingerprint()
    assert a.preregistration_hash() == b.preregistration_hash()
    c = _spec(spec_id="other")
    assert c.fingerprint() != a.fingerprint()


def test_window_ordering_enforced():
    with pytest.raises(SpecError):
        WindowSpec("2026-03-01", "2026-01-01", "2027-01-01", "2027-03-31",
                   "2027-04-01", "2027-06-30")
    with pytest.raises(SpecError):
        WindowSpec("2026-03-01", "2026-12-31", "2027-02-01", "2027-03-31",
                   "2027-01-05", "2027-06-30")


def test_52w_high_window_guard():
    with pytest.raises(SpecError):
        SignalSpec("near_52w_high", high_window_sessions=65)   # documented defect


# ---------------------------------------------------------------------------
# PIT data layer
# ---------------------------------------------------------------------------

def test_decision_availability_gate(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3")
    panel = PitPanel(conn, "nifty50")
    # decision at 2026-04-01 00:15 IST sees only bars available then: through
    # 2026-03-31 (the 2026-04-01 bar becomes available 2026-04-02 00:15)
    got = panel.decision_close("AAA", "2026-04-01T00:15:00+05:30")
    assert got == ("2026-03-31", truth["AAA"]["2026-03-31"][1])
    assert got[0] != "2026-04-01"


def test_momentum_exactness(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3")
    panel = PitPanel(conn, "nifty50")
    ts = "2026-05-04T00:15:00+05:30"           # sees bars through 2026-05-03
    look = 21
    i = panel._bisect_available("AAA", ts)
    rows = panel.series["AAA"]
    end, start = rows[i - 1], rows[i - 1 - look]
    expected = truth["AAA"][end[0]][1] / truth["AAA"][start[0]][1] - 1
    assert end[0] == "2026-05-01"
    assert panel.momentum("AAA", ts, look) == pytest.approx(expected)


def test_near_52w_high_exactness(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3")
    panel = PitPanel(conn, "nifty50")
    ts = "2027-04-01T00:15:00+05:30"            # 252+ sessions of history by then
    win = 252
    for sym in ("AAA", "FFF"):                  # AAA drifts up, FFF drifts down
        i = panel._bisect_available(sym, ts)
        rows = panel.series[sym]
        closes = [truth[sym][r[0]][1] for r in rows[i - win:i]]
        expected = -(max(closes) - closes[-1]) / max(closes)
        got = panel.near_52w_high(sym, ts, win)
        assert got == pytest.approx(expected)
        assert got <= 0                          # distance below/at the high
    assert panel.near_52w_high("AAA", ts, win) == pytest.approx(0.0)  # at high
    assert panel.near_52w_high("FFF", ts, win) < 0                    # below it


def test_signal_abstention_discontinuity_and_short_history(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3")
    panel = PitPanel(conn, "nifty50")
    # SPLIT carries a raw 2:1 halving on 2026-07-15: any lookback window that
    # contains it must ABSTAIN (None), never guess through
    ts = "2026-08-03T00:15:00+05:30"
    assert panel.momentum("SPLIT", ts, 21) is None
    assert panel.near_52w_high("SPLIT", ts, 252) is None
    # before the split, the window is clean and computes
    assert panel.momentum("SPLIT", "2026-07-01T00:15:00+05:30", 21) is not None
    # insufficient history: abstain, never fabricate
    assert panel.momentum("AAA", "2026-03-05T00:15:00+05:30", 21) is None
    # holding disclosure records the discontinuity for held positions
    disc = panel.holding_discontinuities("SPLIT", "2026-07-01", "2026-08-03")
    assert any(d["session"] == SPLIT_DATE for d in disc)


def test_rename_alias_continuity(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3")
    panel = PitPanel(conn, "nifty50")
    # after the rename (2026-10-15), the decision must see pre-rename history
    # traded under REN via the alias closure (bars follow the instrument)
    ts = "2026-10-16T00:15:00+05:30"
    got = panel.momentum("REN2", ts, 21)         # canonical display name input
    assert got is not None                       # only possible with REN bars
    key = panel.key_for("REN2")                  # internal spell-symbol key
    rows = panel.series[key]
    i = panel._bisect_available(key, ts)
    end, start = rows[i - 1], rows[i - 1 - 21]
    assert start[0] < REN_DATE                   # window reaches into old name
    expected = truth["REN"][end[0]][1] / truth["REN"][start[0]][1] - 1
    assert got == pytest.approx(expected)


# ---------------------------------------------------------------------------
# runner mechanics
# ---------------------------------------------------------------------------

def test_runner_determinism_same_result_id(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    spec = _spec()
    a = run_backtest(spec, conn=conn)
    b = run_backtest(spec, conn=conn)
    assert a.result_id == b.result_id
    assert a.months == b.months and a.fills == b.fills


def test_runner_determinism_across_spec_registrations(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    # Two separate registrations of the same rule set carry different
    # registration instants; registration-instant fields (created_at /
    # preregistration_hash) are excluded from the canonical result_id, so a
    # rerun of the same preregistered rule set is id-stable.
    a = run_backtest(_spec(), conn=conn)
    b = run_backtest(_spec(), conn=conn)
    assert a.result_id == b.result_id
    assert a.months == b.months and a.fills == b.fills


def test_boundary_exit_no_overnight_skip(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3")
    res = run_backtest(_spec(), conn=conn)
    labeled = [m for m in res.months if m["gross_month"] is not None]
    assert len(labeled) >= 6
    for a, b in zip(labeled, labeled[1:]):
        assert b["entry_session"] == a["exit_session"]
    # fill-level: exit references the exit session's OWN open (not skipped)
    panel = PitPanel(conn, "nifty50")
    for f in res.fills:
        if not f["exit_extended"]:
            assert f["exit_open_paise"] == panel.bar_on(f["symbol"],
                                                        f["exit_session"])[0]
        assert f["exit_session"] > f["entry_session"]


def test_purge_censoring_no_fold_crossing(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    windows = ("2026-03-01", "2026-10-31", "2026-11-01", "2027-02-28",
               "2027-03-01", "2027-06-30")
    res = run_backtest(_spec(windows=windows), conn=conn, phase="train")
    labeled = [m for m in res.months if m["gross_month"] is not None]
    assert labeled
    # no label matures beyond the phase end: the final entry is censored
    assert max(m["exit_session"] for m in labeled) <= "2026-10-31"
    for f in res.fills:
        assert f["exit_session"] <= "2026-10-31"
    # validation phase starts fresh at its own boundary
    v = run_backtest(_spec(windows=windows), conn=conn, phase="validation")
    vl = [m for m in v.months if m["gross_month"] is not None]
    assert all(m["entry_session"] >= "2026-11-01" for m in vl)
    assert max(m["exit_session"] for m in vl) <= "2027-02-28"


def test_month_rows_carry_eligible_pool(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    res = run_backtest(_spec(), conn=conn)
    for m in res.months:
        if m["gross_month"] is None:
            continue
        pool = m["eligible_gross"]
        assert m["eligible_symbols"], "eligible pool disclosed"
        assert len(pool) >= m["n_chosen"]
        for f in [x for x in res.fills if x["period"] == m["period"]]:
            assert f["symbol"] in pool          # chosen are drawn from the pool


def test_nav_reconciles_from_ledger(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    res = run_backtest(_spec(), conn=conn)
    labeled = [m for m in res.months if m["gross_month"] is not None]
    for m in labeled:
        fills_m = [f for f in res.fills if f["period"] == m["period"]]
        mean_g = sum(f["gross_return"] for f in fills_m) / len(fills_m)
        assert m["gross_month"] == pytest.approx(mean_g)
    for seg in res.labeled_segments:
        seg_set = set(seg)
        rows = [m for m in labeled if m["period"] in seg_set]
        assert len(rows) == len(seg)
        prod = 1.0
        for m in rows:
            prod *= 1 + m["gross_month"]
        nav_row = next(r for r in res.nav["segments"]
                       if r["start"] == seg[0] and r["end"] == seg[-1])
        assert nav_row["gross"] == pytest.approx(prod - 1.0)
    charges = sum(f["accounting"]["charges_total_paise"]
                  for f in res.fills if f["accounting"])
    assert res.costs["charges_total_paise"] == charges
    assert charges > 0                          # fee model actually applied


def test_verified_split_cash_consistent(tmp_path):
    conn, truth = _make_fixture(tmp_path / "f.sqlite3", verified_split=True)
    res = run_backtest(_spec(), conn=conn)      # SPLIT has the top drift -> chosen
    july = [f for f in res.fills if f["period"] == "2026-07"
            and f["symbol"] == "SPLIT"]
    assert july, "SPLIT must be selected in the split month"
    f = july[0]
    assert f["adjustment_basis"] == "ADJUSTED_VERIFIED"
    # raw exit open matches the generator's post-split level
    assert f["exit_open_paise"] == truth["SPLIT"][f["exit_session"]][0]
    # sell is the adverse-slipped raw price DOUBLED (verified factor restates
    # the original share count: 2 post-split shares per pre-split share)
    expected_sell = 2 * math.floor(f["exit_open_paise"] * (1 - 10 / 10_000))
    assert f["sell_paise"] == expected_sell
    # integer-paise budget respected: qty x buy <= per-name allocation
    assert f["quantity"] * f["buy_paise"] <= 10_000_000 // 3
    assert f["accounting"]["sell_turnover_paise"] == f["quantity"] * expected_sell
    assert f["gross_return"] == pytest.approx(expected_sell / f["buy_paise"] - 1)
    # the verified restatement keeps economics interpretable: not blocked
    assert res.price_basis["economics_vs_tri_blocked"] is False
    assert res.status == "RESEARCH"


def test_unverified_action_blocks_economics(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3", verified_split=False)
    res = run_backtest(_spec(), conn=conn)
    july = [f for f in res.fills if f["period"] == "2026-07"
            and f["symbol"] == "SPLIT"]
    assert july and july[0]["adjustment_basis"] == "RAW_UNADJUSTED"
    assert res.price_basis["economics_vs_tri_blocked"] is True
    assert res.status == "DATA_BLOCKED"
    assert any("left RAW" in w for w in res.warnings)


def test_weak_membership_disclosed_and_blocked(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3", weak=True)
    res = run_backtest(_spec(), conn=conn)
    labeled = [m for m in res.months if m["gross_month"] is not None]
    assert labeled
    assert all(m["membership_status"] == "PARTIAL" for m in labeled)
    assert all((m.get("weak_rows_included") or 0) >= 1 for m in labeled)
    assert res.status == "DATA_BLOCKED"


def test_hole_month_breaks_segments(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3", hole=True)
    res = run_backtest(_spec(), conn=conn)
    assert len(res.labeled_segments) == 2
    starts = {seg[0] for seg in res.labeled_segments}
    assert "2026-10" in starts                  # post-hole segment
    assert res.continuous_chain_blocked         # whole-window NAV withheld
    assert all(a.get("cause") for a in res.abstained_months)
    # NO single whole-window compounded NAV is fabricated across the gap
    assert res.nav["whole_window_continuous"] is None


# ---------------------------------------------------------------------------
# negative controls, costs, sweeps
# ---------------------------------------------------------------------------

def test_leak_control_caught_and_rejected(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    spec = _spec(family="leak_control", control=True, spec_id="lab.leak")
    res = run_backtest(spec, conn=conn)
    rep = challenge_finding(res, n_placebo=10, conn=conn)
    avail = next(c for c in rep.checks if c["check"] == "availability_provenance")
    assert avail["status"] == "FAIL"
    assert "future" in json.dumps(avail).lower()
    assert rep.verdict == "REJECTED"
    assert "challenger caught" in rep.verdict_reason


def test_noise_control_rejected(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    spec = _spec(family="noise_control", control=True, spec_id="lab.noise")
    res = run_backtest(spec, conn=conn)
    rep = challenge_finding(res, n_placebo=10, conn=conn)
    assert rep.verdict == "REJECTED"
    assert spec.signal.family in rep.verdict_reason


def test_cost_scenarios_monotone(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    sc = run_cost_scenarios(_spec(bps=10), conn, None)
    assert sc["base"] and sc["double_cost"]
    assert sc["double_cost"]["net_product"] <= sc["base"]["net_product"]
    assert sc["double_cost"]["charges_paise"] != sc["base"]["charges_paise"]
    assert sc["base_result_id"] != sc["double_result_id"]


def test_sweep_bounded_complete_holdout_free(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    base = _spec()
    grid = {"lookback_sessions": [21, 4], "skip_sessions": [0, 3]}
    sweep = run_sweep(base, grid, conn=conn)
    assert sweep.n_trials == 4 and len(sweep.variants) == 4
    assert sweep.n_failed == 2                  # lookback 4 < minimum 5: recorded
    failed = [v for v in sweep.variants if not v["ok"]]
    assert failed and all("lookback_sessions" in v["error"] for v in failed)
    assert sweep.used_holdout is False
    assert all(v["result_id"] or not v["ok"] for v in sweep.variants)
    with pytest.raises(SpecError):
        run_sweep(base, {"lookback_sessions": list(range(5, 65)),
                         "top_k": [1, 2]}, conn=conn)      # cardinality 120 > 64
    with pytest.raises(SpecError):
        run_sweep(base, {"rebalance": ["monthly"]}, conn=conn)  # not allowlisted


def test_holdout_without_seal_fails_integrity(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    res = run_backtest(_spec(), conn=conn, phase="holdout")
    rep = challenge_finding(res, conn=conn, holdout_seal=None)
    h = next(c for c in rep.checks if c["check"] == "holdout_integrity")
    assert h["status"] == "FAIL"
    assert rep.verdict == "DATA_BLOCKED"
    # with a registered seal the same evaluation passes integrity
    rep2 = challenge_finding(res, conn=conn,
                             holdout_seal={"sealed_before_runs": True,
                                           "sealed_at": "2026-01-01T00:00:00+00:00"})
    h2 = next(c for c in rep2.checks if c["check"] == "holdout_integrity")
    assert h2["status"] == "PASS"


# ---------------------------------------------------------------------------
# journal discipline
# ---------------------------------------------------------------------------

def test_journal_seal_reveal_discipline(tmp_path):
    conn, _ = _make_fixture(tmp_path / "f.sqlite3")
    jr = ResearchJournal(tmp_path / "journal.jsonl")
    with pytest.raises(JournalError):
        jr.reveal_holdout("lab.h1", 1, runs_evaluated=[])      # no seal
    jr.seal_holdout("lab.h1", 1, ("2027-04-01", "2027-06-30"))
    with pytest.raises(JournalError):
        jr.seal_holdout("lab.h1", 1, ("2027-04-01", "2027-06-30"))  # double seal
    spec = _spec()
    jr.preregister(spec.to_payload())
    res = run_backtest(spec, conn=conn)
    jr.register_run(res)
    rep = challenge_finding(res, n_placebo=5, conn=conn)
    jr.register_challenge(rep, strategy_id="lab.h1", version=1)
    st = jr.status("lab.h1", 1)
    assert st["sealed"] and not st["revealed"]
    assert st["holdout_window"] == ["2027-04-01", "2027-06-30"]
    assert len(st["runs"]) == 1 and len(st["challenges"]) == 1
    assert st["chain_intact"]
    jr.reveal_holdout("lab.h1", 1, runs_evaluated=[res.result_id])
    with pytest.raises(JournalError):
        jr.reveal_holdout("lab.h1", 1, runs_evaluated=[])      # single reveal
    st2 = jr.status("lab.h1", 1)
    assert st2["revealed"] and st2["runs_before_reveal"] == [res.result_id]
    # a different version stays unsealed
    assert jr.status("lab.h1", 2)["sealed"] is False


def test_journal_chain_tamper_detection(tmp_path):
    jr = ResearchJournal(tmp_path / "journal.jsonl")
    jr.seal_holdout("t", 1, ("a", "b"))
    jr.preregister({"spec_id": "t", "version": 1})
    ok, why = jr.verify_chain()
    assert ok, why
    path = tmp_path / "journal.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    doc = json.loads(lines[0])
    doc["window"] = ["x", "y"]                  # rewrite history
    lines[0] = json.dumps(doc, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    jr2 = ResearchJournal(str(path))
    jr2._entries = None                          # force reload
    ok2, why2 = jr2.verify_chain()
    assert not ok2


def test_journal_status_tool_shape(tmp_path):
    jr = ResearchJournal(tmp_path / "j.jsonl")
    jr.seal_holdout("s", 3, ("2027-04-01", "2027-06-30"))
    from quantplus_intelligence.research_v3.lab import research_journal_status
    st = research_journal_status(jr, "s", 3)
    assert {"strategy_id", "version", "sealed", "revealed", "holdout_window",
            "preregistered", "runs", "challenges", "chain_intact",
            "n_events"} <= set(st)
