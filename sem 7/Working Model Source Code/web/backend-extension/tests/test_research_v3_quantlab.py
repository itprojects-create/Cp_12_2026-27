"""W3 quantlab tests — hermetic, deterministic, fixture-backed (W2 style).

The fixture is a synthetic micro-warehouse (never the real archive):
integer-paise weekday bars for a few members over 2020-2022 (outside the
quarantined revealed W2 holdout), a verified 2:1 split, an undated rename with
alias continuity, zero-volume bars for missingness, an official-shape TRI
benchmark at a flat 1000.0 (so benchmark_relative == stock gross), and a short
post-holdout 2026-10 fee-effective tail so the NET path (verified schedule) is
also exercised. Every test asserts typed behavior; nothing is silently repaired.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab import ResearchJournal
from quantplus_intelligence.research_v3.quantlab import (
    FeaturePanel, build_label, fit_predict, make_folds, purge_ok,
    set_session_index)
from quantplus_intelligence.research_v3.quantlab.adapter import (
    challenge_model_run, model_spec_payload, preregister_model_suite,
    register_model_challenge, register_model_run, top_k_candidates)
from quantplus_intelligence.research_v3.quantlab.contracts import (
    ADMISSIBLE, DATA_BLOCKED_UNVERIFIED_ACTIONS, ModelRun, ReturnLabel,
    TrainFold)
from quantplus_intelligence.research_v3.quantlab.folds import (
    EMBARGO_SESSIONS, REVEALED_W2_HOLDOUT, _SESSION_INDEX)
from quantplus_intelligence.research_v3.quantlab.metrics import (
    _rank, brier, day_clustered_rank_ic, group_by_day, mae)
from quantplus_intelligence.research_v3.quantlab.models import (
    CORE_LINEAR_FEATURES, RIDGE_CONFIG, _standardizer)

IST = timezone(timedelta(hours=5, minutes=30))
SPLIT_DATE = "2021-09-15"          # inside the 2020-2022 bar span
REN_DATE = "2022-06-15"
FEE_TAIL = ("2026-10-05", "2026-10-16")   # post-holdout, fee-schedule covered

DRIFTS = {"MOM": 0.0010, "REV": -0.0005, "SPLIT": 0.0020, "REN": 0.0003}
BASES = {"MOM": 150_00, "REV": 250_00, "SPLIT": 400_00, "REN": 210_00}


def _sessions() -> list[str]:
    out, d = [], date(2020, 1, 6)
    while d <= date(2022, 12, 30):
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    out += ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
            "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14",
            "2026-10-15", "2026-10-16"]
    return out


SESSIONS = _sessions()


def _make_fixture(path, *, verified_split=True, zero_volume=False):
    """Build the micro-warehouse. Returns (conn, truth)."""
    conn = W.connect(path)
    truth: dict[str, dict[str, tuple[int, int]]] = {}
    for sym, g in DRIFTS.items():
        series: dict[str, tuple[int, int]] = {}
        c_prev = BASES[sym]
        for s in SESSIONS:
            close = round(c_prev * (1 + g))
            if sym == "SPLIT" and s == SPLIT_DATE:
                close = round(close * 0.5)      # single 2:1 halving
            open_ = round(c_prev * 0.5) if (sym == "SPLIT" and s == SPLIT_DATE) \
                else c_prev
            bar_sym = "REN2" if (sym == "REN" and s >= REN_DATE) else sym
            avail = (datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=IST)
                     + timedelta(days=1, minutes=15)).isoformat()
            vol = 0 if (zero_volume and sym == "REV") else 1000
            conn.execute(
                "INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s, bar_sym, "EQ", "ISIN" + sym, open_, max(open_, close),
                 min(open_, close), close, c_prev, vol, 100000, 10,
                 "fixture", "2026-01-01", avail, "fixture raw", "FIXTURE"))
            series[s] = (open_, close)
            c_prev = close
        truth[sym] = series
    for sym in DRIFTS:
        conn.execute(
            "INSERT INTO membership_spells VALUES (?,?,?,?,?,?,?,?,?)",
            ("999", "nifty50", sym, "2020-01-01", None, "press_release",
             1, "fixture", "fixture attribution (test)"))
    conn.execute("INSERT INTO symbol_renames VALUES "
                 "('REN','REN2','2022-06-15','fixture')")
    if verified_split:
        conn.execute("INSERT INTO corporate_actions VALUES "
                     "('SPLIT','split','2021-09-15',0.5,NULL,NULL,'fixture',1)")
    for s in SESSIONS:
        conn.execute("INSERT INTO benchmark_bars VALUES "
                     "('NIFTY50_TRI',?,1000.0,'fixture','2026-01-01',"
                     "'official fixture TRI (flat)')", (s,))
    conn.commit()
    return conn, truth


@pytest.fixture()
def lab(tmp_path):
    conn, truth = _make_fixture(tmp_path / "quantlab.sqlite3")
    panel = FeaturePanel(conn, "nifty50")
    return conn, truth, panel


def _dts(session: str) -> str:
    d = date.fromisoformat(session[:10]) + timedelta(days=1)
    return f"{d.isoformat()}T00:15:00+05:30"


# ---------------------------------------------------------------------------
# 1. PIT gating: no future-dependent feature, leakage attempts fail closed
# ---------------------------------------------------------------------------
def test_snapshot_pit_gating(lab):
    _conn, truth, panel = lab
    snap_at = {s: panel.snapshot("MOM", _dts(s)) for s in
               SESSIONS[121:123] + SESSIONS[300:301]}
    for s, snap in snap_at.items():
        assert snap.decision_session == s          # visible bar is S's own
        # ret_20 must equal the truth-based 20-session close-to-close return
        i = SESSIONS.index(s)
        expected = truth["MOM"][s][1] / truth["MOM"][SESSIONS[i - 20]][1] - 1
        assert snap.features["ret_20"] == pytest.approx(expected, abs=1e-9)
        assert "ret_120" in snap.features          # 500+ session history

    # a cutoff BEFORE any bar: typed full abstention, no fabricated values
    empty = panel.snapshot("MOM", "2020-01-01T00:15:00+05:30")
    assert empty.features == {} and empty.decision_session == ""
    assert set(empty.abstained_features) >= {"ret_5", "prox_252", "vol_20"}

    # a LATER cutoff sees the NEXT bar only after it becomes available:
    # nothing from session S+1 leaks into a cutoff at S+1 T00:15 (S's bar
    # becomes available exactly then)
    s = SESSIONS[300]
    early = panel.snapshot("MOM", _dts(s))
    late = panel.snapshot("MOM", _dts(SESSIONS[301]))
    assert early.decision_session == s and late.decision_session == SESSIONS[301]
    assert late.features["ret_5"] != early.features["ret_5"]


def test_leakage_attempt_fails_closed(lab):
    """A window straddling an action-shaped discontinuity refuses the feature
    (returns None) — the corruption can never enter the feature vector."""
    _conn, _truth, panel = lab
    i = SESSIONS.index(SPLIT_DATE)
    snap = panel.snapshot("SPLIT", _dts(SESSIONS[i + 10]))
    # every feature whose lookback window CONTAINS the split discontinuity
    # refuses; short windows entirely after the split stay computable
    for name in ("ret_20", "ret_60", "ret_120", "prox_252", "vol_20",
                 "drawdown_60"):
        assert name not in snap.features
        assert "discontinuity" in snap.abstained_features[name]
    assert "ret_5" in snap.features          # its window lies after the split
    # clean window on the same symbol is fine
    snap_ok = panel.snapshot("SPLIT", _dts(SESSIONS[i + 60]))
    assert "ret_20" in snap_ok.features


# ---------------------------------------------------------------------------
# 2. Split/demerger gaps do not become spurious alpha
# ---------------------------------------------------------------------------
def test_split_label_data_blocked_not_alpha(lab):
    _conn, _truth, panel = lab
    i = SESSIONS.index(SPLIT_DATE)
    # decision 20 sessions before the split; entry lands ~19 sessions before
    # and the h20 exit crosses the split -> contamination, never "alpha"
    lab_ret = build_label(panel, "SPLIT", _dts(SESSIONS[i - 20]), 20)
    assert lab_ret.admissibility == "DATA_BLOCKED_ACTION_WINDOW"
    assert lab_ret.contamination, "split discontinuity must be disclosed"
    assert lab_ret.gross_return is not None        # raw number, disclosed
    assert not lab_ret.usable_for_ic               # excluded from statistics
    # the SAME typing applies whether the action row is verified or not:
    # raw-price windows are conservatively blocked either way
    conn_u, _truth_u = _make_fixture(_split_unverified_path(), verified_split=False)
    panel_u = FeaturePanel(conn_u, "nifty50")
    lab_u = build_label(panel_u, "SPLIT", _dts(SESSIONS[i - 20]), 20)
    assert lab_u.admissibility == "DATA_BLOCKED_ACTION_WINDOW"


def _split_unverified_path():
    import tempfile
    return tempfile.mkstemp(suffix=".sqlite3")[1]


# ---------------------------------------------------------------------------
# 3. Missing calendar sessions are never silently stitched
# ---------------------------------------------------------------------------
def test_archive_gap_not_stitched(tmp_path):
    conn, _truth = _make_fixture(tmp_path / "hole.sqlite3")
    # remove a full month for one symbol (archive gap for that name)
    hole = [s for s in SESSIONS if s[:7] == "2022-03"]
    conn.execute(
        f"DELETE FROM daily_bars WHERE symbol='MOM' AND session IN "
        f"({','.join('?' * len(hole))})", hole)
    conn.commit()
    panel = FeaturePanel(conn, "nifty50")
    i = SESSIONS.index(hole[-1])
    snap = panel.snapshot("MOM", _dts(SESSIONS[i + 1]))
    assert "ret_20" not in snap.features           # gap inside lookback: refuse
    assert "ret_20" in snap.abstained_features


def test_exit_extension_labelled_not_silent(tmp_path):
    """A SHORT gap: the exit target session has no bar, so the exit extends to
    the next available close WITH exit_extended=True (never a silent skip)."""
    conn, _truth = _make_fixture(tmp_path / "shortgap.sqlite3")
    gap = [s for s in SESSIONS if "2022-05-02" <= s <= "2022-05-06"]
    conn.execute(
        f"DELETE FROM daily_bars WHERE symbol='MOM' AND session IN "
        f"({','.join('?' * len(gap))})", gap)
    conn.commit()
    panel = FeaturePanel(conn, "nifty50")
    gi = SESSIONS.index(gap[0])
    # entry lands at gi-16, so the h20 exit target is gi+4 = inside the gap
    lab_ret = build_label(panel, "MOM", _dts(SESSIONS[gi - 17]), 20)
    assert lab_ret.status == "OK"
    assert lab_ret.exit_extended is True
    assert lab_ret.exit_session > SESSIONS[gi + 4]    # beyond the missing target
    assert lab_ret.exit_session in panel.sessions     # a real observed session


# ---------------------------------------------------------------------------
# 4. Purge / embargo / holdout quarantine
# ---------------------------------------------------------------------------
def test_purge_and_embargo(lab):
    _conn, _truth, panel = lab
    set_session_index(panel.sessions)
    ix = _SESSION_INDEX
    val_start = "2022-07-01"
    vs_ix = ix[val_start]
    assert not purge_ok(None, val_start)                    # no exit -> never
    assert not purge_ok("9999-12-31", val_start)            # unknown -> fail closed
    assert not purge_ok(panel.sessions[vs_ix - 5], val_start)   # inside embargo
    assert purge_ok(panel.sessions[vs_ix - 11], val_start)      # beyond embargo
    assert EMBARGO_SESSIONS == 10


def test_holdout_quarantine_raises(lab):
    _conn, _truth, panel = lab
    set_session_index(panel.sessions)
    assert REVEALED_W2_HOLDOUT == ("2024-06-21", "2026-09-17")
    # the real fixture span (2020-2022) does NOT touch the holdout
    folds = make_folds(panel.sessions, "2020-01-06", "2022-01-03",
                       "2022-12-30", 4)
    assert [f.fold_id for f in folds] == ["wf1", "wf2", "wf3", "wf4"]
    # a span intersecting the revealed W2 holdout is REFUSED outright
    with pytest.raises(ValueError, match="quarantined"):
        make_folds(panel.sessions, "2025-01-01", "2025-06-01", "2026-01-01", 2)
    with pytest.raises(ValueError, match="quarantined"):
        make_folds(panel.sessions, "2026-08-01", "2026-08-15", "2026-09-30", 2)


def test_fold_tiling_and_fingerprint(lab):
    _conn, _truth, panel = lab
    set_session_index(panel.sessions)
    folds = make_folds(panel.sessions, "2020-01-06", "2022-01-03",
                       "2022-12-30", 4)
    covered = [s for f in folds
               for s in panel.sessions if f.val_sessions[0] <= s <= f.val_sessions[1]]
    assert len(covered) == len(set(covered))              # no overlap
    assert len(covered) > 0 and folds[0].embargo_sessions == 10
    # canonical fold identity is stable and deterministic
    again = make_folds(panel.sessions, "2020-01-06", "2022-01-03",
                       "2022-12-30", 4)
    assert [f.fold_id_hash for f in again] == [f.fold_id_hash for f in folds]


# ---------------------------------------------------------------------------
# 5. Labels: no same-close fill, no-trade states, typed economics
# ---------------------------------------------------------------------------
def test_label_no_same_close_fill(lab):
    _conn, _truth, panel = lab
    s = SESSIONS[100]
    lab_ret = build_label(panel, "MOM", _dts(s), 5)
    assert lab_ret.status == "OK" and lab_ret.admissibility == ADMISSIBLE
    assert lab_ret.entry_session > s                       # never the known close
    assert lab_ret.decision_session == s
    # benchmark basis mismatch is TYPED; the raw diagnostic is separate
    assert lab_ret.benchmark_relative == "DATA_BLOCKED_BASIS_MISMATCH"
    assert isinstance(lab_ret.benchmark_relative_raw, float)
    # fee schedule does not cover 2021 -> net is None, typed status
    assert lab_ret.charges_status == "SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE"
    assert lab_ret.net_absolute_paise is None


def test_label_fee_effective_tail_has_real_net(lab):
    _conn, _truth, panel = lab
    lab_ret = build_label(panel, "MOM", _dts("2026-10-05"), 5)
    assert lab_ret.status == "OK" and lab_ret.admissibility == ADMISSIBLE
    assert lab_ret.charges_status == "OK"
    assert isinstance(lab_ret.net_absolute_paise, int)     # real accounting


def test_label_no_trade_states(lab):
    _conn, _truth, panel = lab
    # decision before history / unknown symbol -> NO_DECISION_BASELINE
    lab_ret = build_label(panel, "MOM", "2020-01-01T00:15:00+05:30", 5)
    assert lab_ret.status == "NO_DECISION_BASELINE"
    assert not lab_ret.usable_for_ic
    # history ends before the horizon -> NO_FILL
    lab_end = build_label(panel, "MOM", _dts(SESSIONS[-1]), 60)
    assert lab_end.status in ("NO_FILL", "NO_DECISION_BASELINE")
    assert not lab_end.usable_for_ic


def test_rename_alias_continuity(lab):
    _conn, truth, panel = lab
    assert panel.key_for("REN2") == "REN"                  # alias resolves
    assert panel.key_for("REN") == "REN"
    # bars follow the instrument across the rename: momentum before/after the
    # rename is continuous (no invented break)
    i = SESSIONS.index(REN_DATE)
    snap = panel.snapshot("REN", _dts(SESSIONS[i + 30]))
    j = SESSIONS.index(SESSIONS[i + 30])
    expected = truth["REN"][SESSIONS[j]][1] / truth["REN"][SESSIONS[j - 20]][1] - 1
    assert snap.features["ret_20"] == pytest.approx(expected, abs=1e-9)


def test_zero_volume_missingness(tmp_path):
    conn, _truth = _make_fixture(tmp_path / "vol.sqlite3", zero_volume=True)
    panel = FeaturePanel(conn, "nifty50")
    snap = panel.snapshot("REV", _dts(SESSIONS[300]))
    assert "volume_ratio_20" not in snap.features
    assert "volume_ratio_20" in snap.missing
    assert snap.abstained_features["volume_ratio_20"] == "visible volume unavailable"
    assert "liquidity_20" in snap.missing


def test_vector_completeness_rules(lab):
    _conn, _truth, panel = lab
    snap = panel.snapshot("MOM", _dts(SESSIONS[300]))
    v = snap.vector(["ret_5", "ret_20"])
    assert len(v) == 2
    with pytest.raises(ValueError):
        snap.vector(["ret_5", "volume_ratio_20_none_such"])
    vn = snap.vector_nan(["ret_5", "volume_ratio_20_none_such"])
    assert vn[0] is not None and vn[1] is None


# ---------------------------------------------------------------------------
# 6. Metrics: day-clustered uncertainty, never pooled rows
# ---------------------------------------------------------------------------
def test_day_clustered_rank_ic(lab):
    days = {f"d{i}": {f"s{k}": float(k) for k in range(6)} for i in range(6)}
    res = day_clustered_rank_ic(days, dict(days))
    assert res["n_days"] == 6 and res["mean_ic"] == pytest.approx(1.0)
    assert res["ic_t_day_clustered"] is None               # zero variance
    assert "correlated" in res["note"]
    # a thin day (4 names) is excluded and disclosed
    thin = {"dthin": {f"s{k}": float(k) for k in range(4)}}
    res2 = day_clustered_rank_ic({**thin, **days}, {**thin, **days})
    assert res2["per_day"]["dthin"]["n"] == 4
    assert res2["per_day"]["dthin"]["ic"] is None
    assert "n<5" in res2["per_day"]["dthin"]["note"]
    assert res2["n_days"] == 6
    # inverted order -> IC -1
    inv = {d: {s: -v for s, v in m.items()} for d, m in days.items()}
    assert day_clustered_rank_ic(inv, days)["mean_ic"] == pytest.approx(-1.0)


def test_rank_ties_average():
    assert _rank([1.0, 1.0, 2.0]) == [1.5, 1.5, 3.0]


def test_brier_and_mae():
    y = {"d1": {"a": 1, "b": 0}}
    assert brier({"d1": {"a": 1.0, "b": 0.0}}, y)["brier"] == 0.0
    r = brier({"d1": {"a": 0.5, "b": 0.5}}, y)
    assert r["brier"] == 0.25 and r["base_rate"] == 0.5
    m = mae({"d1": {"a": 0.02, "b": -0.01}}, {"d1": {"a": 0.01, "b": 0.01}})
    assert m["mae"] == pytest.approx(0.015) and m["hit_rate"] == 0.5
    assert brier({}, {})["brier"] is None                  # no pairs -> typed None


def test_group_by_day_filter():
    rows = [{"session": "d1", "symbol": "a", "pred": 1.0},
            {"session": "d1", "symbol": "b", "pred": None},
            {"session": "d2", "symbol": "a", "pred": 0.5}]
    g = group_by_day(rows, "pred")
    assert g == {"d1": {"a": 1.0}, "d2": {"a": 0.5}}


# ---------------------------------------------------------------------------
# 7. Models: fixed configs, train-only normalization, typed failures
# ---------------------------------------------------------------------------
def _rows(panel, sessions, horizon=5, symbols=("MOM", "REV")):
    out = []
    for sym in symbols:
        for s in sessions:
            snap = panel.snapshot(sym, _dts(s))
            l = build_label(panel, sym, _dts(s), horizon)
            out.append({"session": s, "symbol": sym, "snapshot": snap,
                        "y": l.gross_return if l.usable_for_ic else None})
    return out


def test_ridge_logistic_hgb_fixture(lab):
    _conn, _truth, panel = lab
    set_session_index(panel.sessions)
    train = [r for r in _rows(panel, panel.sessions[:len(panel.sessions) // 2])]
    val = _rows(panel, panel.sessions[len(panel.sessions) // 2:len(panel.sessions) // 2 + 40])
    # purge applies upstream of fit_predict; here rows are pre-purged in kind
    train = [r for r in train if r["y"] is not None]
    val = [r for r in val if r["y"] is not None]
    assert len(train) > 200, "fixture must exceed the minimum-rows gate"

    res = fit_predict("ridge", train, val, 5, RIDGE_CONFIG)
    assert res["ok"] and res["family"] == "ridge"
    assert res["diagnostics"]["train_r2"] > -1.0
    assert all(-1e6 < p["pred"] < 1e6 for p in res["predictions"])

    res_log = fit_predict("logistic", train, val, 5, {"C": 1.0, "seed": 7})
    assert res_log["ok"]
    assert all(0.0 <= p["pred"] <= 1.0 for p in res_log["predictions"])

    res_hgb = fit_predict("hgb", train, val, 5, {"max_iter": 20, "seed": 7})
    assert res_hgb["ok"]
    assert all(0.0 <= p["pred"] <= 1.0 for p in res_hgb["predictions"])

    res_clim = fit_predict("climatology_binary", train, val, 5)
    assert res_clim["ok"] and all(p["pred"] == 0.5 for p in res_clim["predictions"])

    res_mom = fit_predict("momentum_rank", train, val, 5, {"feature": "ret_60"})
    assert res_mom["ok"] and len(res_mom["predictions"]) > 0


def test_complete_row_exclusion_vs_nan_tolerance(tmp_path):
    conn2, _t2 = _make_fixture(tmp_path / "vol2.sqlite3", zero_volume=True)
    panel2 = FeaturePanel(conn2, "nifty50")
    train = _rows(panel2, panel2.sessions[:500])
    val = _rows(panel2, panel2.sessions[500:510])
    train = [r for r in train if r["y"] is not None]
    val = [r for r in val if r["y"] is not None]
    r_ridge = fit_predict("ridge", train, val, 5, RIDGE_CONFIG)
    assert r_ridge["ok"]
    # REV rows lack volume_ratio_20 -> complete-row family must exclude them
    assert r_ridge["excluded_val_rows"] >= 5
    r_hgb = fit_predict("hgb", train, val, 5, {"max_iter": 20, "seed": 7})
    assert r_hgb["ok"] and r_hgb["excluded_val_rows"] == 0   # NaN-tolerant


def test_typed_failures(lab):
    _conn, _truth, panel = lab
    tiny = _rows(panel, panel.sessions[:30])               # far below 200 rows
    res = fit_predict("ridge", tiny, tiny[:5], 5, RIDGE_CONFIG)
    assert not res["ok"] and "insufficient training rows" in res["error"]
    res2 = fit_predict("no_such_family", tiny, tiny[:5], 5)
    assert not res2["ok"] and res2["error"] == "unknown family"


def test_train_only_standardizer():
    import numpy as np
    tr = np.array([[0.0, 10.0], [2.0, 14.0]])
    mu, sd = _standardizer(tr)
    assert mu.tolist() == [1.0, 12.0]
    assert sd.tolist() == [1.0, 2.0]
    # the standardizer never sees validation statistics (signature has none)
    tr2 = np.array([[100.0, 0.0], [104.0, 4.0]])
    mu2, sd2 = _standardizer(tr2)
    assert mu2.tolist() == [102.0, 2.0] and sd2.tolist() == [2.0, 2.0]


# ---------------------------------------------------------------------------
# 8. Determinism: run ids and predictions are pure functions of inputs
# ---------------------------------------------------------------------------
def test_run_id_determinism(lab):
    fold = TrainFold("wf1", ("2021-01-04", "2022-01-03"), ("2022-01-03", "2022-06-30"), 10)
    rid1 = ModelRun.compute_run_id("ridge", RIDGE_CONFIG, fold, "FH", "LH", 20)
    rid2 = ModelRun.compute_run_id("ridge", RIDGE_CONFIG, fold, "FH", "LH", 20)
    assert rid1 == rid2 and len(rid1) == 64
    rid3 = ModelRun.compute_run_id("ridge", {**RIDGE_CONFIG, "alpha": 2.0},
                                   fold, "FH", "LH", 20)
    assert rid3 != rid1
    # the horizon is part of the identity: h5/h20/h60 runs of the same
    # family+fold (different fitted prediction sets) never share an id
    rid_h5 = ModelRun.compute_run_id("ridge", RIDGE_CONFIG, fold, "FH", "LH", 5)
    rid_h60 = ModelRun.compute_run_id("ridge", RIDGE_CONFIG, fold, "FH", "LH", 60)
    assert len({rid1, rid_h5, rid_h60}) == 3
    fold2 = TrainFold("wf2", ("a", "b"), ("c", "d"), 10)
    assert ModelRun.compute_run_id("ridge", RIDGE_CONFIG, fold2, "FH", "LH",
                                   20) != rid1


def test_fit_predict_deterministic(lab):
    _conn, _truth, panel = lab
    cut = len(panel.sessions) // 2
    train = [r for r in _rows(panel, panel.sessions[:cut]) if r["y"] is not None]
    val = [r for r in _rows(panel, panel.sessions[cut:cut + 30]) if r["y"] is not None]
    a = fit_predict("ridge", train, val, 5, RIDGE_CONFIG)
    b = fit_predict("ridge", train, val, 5, RIDGE_CONFIG)
    assert a["predictions"] == b["predictions"]
    assert a["diagnostics"] == b["diagnostics"]


# ---------------------------------------------------------------------------
# 9. Challenger battery and journal integration
# ---------------------------------------------------------------------------
def _pooled_run(pred_by_day):
    preds = [{"session": d, "symbol": s, "pred": v}
             for d, m in pred_by_day.items() for s, v in m.items()]
    return preds


def test_challenger_rejects_noise_accepts_signal():
    days = {f"d{i}": {f"s{k}": float(k) for k in range(6)} for i in range(6)}
    strong = challenge_model_run(
        type("R", (), {"run_id": "r-strong",
                       "predictions": _pooled_run(days)})(), dict(days))
    assert strong["verdict"] == "RESEARCH_DIAGNOSTIC"
    assert strong["n_fail"] == 0
    # inverted predictions (perfect negative IC) cannot beat the 90th percentile
    inv = {d: {s: -v for s, v in m.items()} for d, m in days.items()}
    weak = challenge_model_run(
        type("R", (), {"run_id": "r-weak",
                       "predictions": _pooled_run(inv)})(), dict(days))
    assert weak["verdict"] == "REJECTED"
    assert weak["n_fail"] >= 1
    # typed cost + holdout blocks are present in every report
    for rep in (strong, weak):
        checks = {c["check"]: c for c in rep["checks"]}
        assert checks["cost_sensitivity"]["status"] == "INCONCLUSIVE"
        assert checks["holdout_integrity"]["status"] == "PASS"


def test_journal_integration(tmp_path):
    jr = ResearchJournal(str(tmp_path / "wave3_research_journal.jsonl"))
    specs = [model_spec_payload("wave3.ridge.h20", 1, "ridge", 20,
                                "hypothesis (test)", RIDGE_CONFIG),
             model_spec_payload("wave3.climatology_binary.h20", 1,
                                "climatology_binary", 20, "control",
                                {"constant": 0.5}, negative_control=True)]
    pre = preregister_model_suite(jr, specs)
    assert len(pre) == 2
    fold = TrainFold("wf1", ("a", "b"), ("c", "d"), 10)
    run = ModelRun(
        run_id=ModelRun.compute_run_id("ridge", RIDGE_CONFIG, fold, "F", "L", 20),
        family="ridge", config=RIDGE_CONFIG, horizon_sessions=20, fold=fold,
        feature_names=("ret_20",), feature_hash="F", label_hash="L",
        n_train_rows=10, n_train_days=5, n_val_rows=4, n_val_days=4,
        n_excluded_rows=0, predictions=({"session": "c", "symbol": "MOM",
                                         "pred": 0.1},),
        abstentions=(), diagnostics={}, warnings=())
    register_model_run(jr, run)
    rep = challenge_model_run(
        type("R", (), {"run_id": run.run_id, "predictions": [
            {"session": "c", "symbol": "MOM", "pred": 0.1}]})(),
        {"c": {"MOM": 0.01}})
    register_model_challenge(jr, run, rep)
    ok, why = jr.verify_chain()
    assert ok, why
    entries = jr._load()
    assert [e["event"] for e in entries] == [
        "SPEC_PREREGISTERED", "SPEC_PREREGISTERED", "RUN_REGISTERED",
        "CHALLENGE_REGISTERED"]
    assert entries[2]["result_id"] == run.run_id
    # negative control is recorded on the control spec
    assert entries[1]["negative_control"] is True


def test_spec_payload_research_only():
    p = model_spec_payload("wave3.momentum_rank.h20", 1, "momentum_rank", 20,
                           "hypothesis", {"feature": "ret_60"})
    assert p["authority"] == "RESEARCH_ONLY" and p["capital_sterile"] is True
    assert p["declared_negative_control"] is False
    p_ctl = model_spec_payload("wave3.climatology_binary.h20", 1,
                               "climatology_binary", 20, "control",
                               {"constant": 0.5}, negative_control=True)
    assert p_ctl["declared_negative_control"] is True


def test_top_k_candidates_research_only(lab):
    _conn, _truth, panel = lab
    label_by_day = {"d1": {f"M{i}": float(i) for i in range(6)}}
    preds = [{"session": "d1", "symbol": f"M{i}", "pred": float(i)}
             for i in range(6)]
    run = type("R", (), {"run_id": "r", "predictions": preds})()
    cands = top_k_candidates(run, label_by_day, k=3)
    assert len(cands) == 3
    assert all(c["authority"] == "RESEARCH_ONLY" for c in cands)
    assert [c["rank"] for c in cands] == [1, 2, 3]
    assert all(c["in_admissible_labels"] for c in cands)
    # abstentions: a symbol with no prediction is never filled
    cands2 = top_k_candidates(type("R", (), {"run_id": "r", "predictions": [
        {"session": "d1", "symbol": "M0", "pred": 1.0}]})(), label_by_day, k=3)
    assert [c["symbol"] for c in cands2] == ["M0"]


# ---------------------------------------------------------------------------
# 10. Contracts carry provenance and typed blockers
# ---------------------------------------------------------------------------
def test_return_label_provenance(lab):
    _conn, _truth, panel = lab
    lab_ret = build_label(panel, "MOM", _dts(SESSIONS[100]), 5)
    assert isinstance(lab_ret, ReturnLabel)
    assert lab_ret.source_id == "nse_eod_bhavcopy_2015_2026_full"
    assert lab_ret.horizon_sessions == 5
    assert lab_ret.admissibility in (ADMISSIBLE, DATA_BLOCKED_UNVERIFIED_ACTIONS,
                                     "DATA_BLOCKED_ACTION_WINDOW", "NO_LABEL")
    dataclass_fields = {f for f in ReturnLabel.__dataclass_fields__}
    assert {"gross_return", "net_absolute_paise", "charges_status",
            "benchmark_relative", "contamination"} <= dataclass_fields


def test_snapshot_provenance(lab):
    _conn, _truth, panel = lab
    snap = panel.snapshot("MOM", _dts(SESSIONS[300]))
    assert snap.source_class == "OFFICIAL_EXCHANGE_RECORD"
    assert snap.reconstruction_label == "RETROSPECTIVE"
    assert "official NSE EOD" in snap.rights_label
    assert snap.universe == "nifty50"
    assert len(snap.snapshot_id) == 64
    # feature-snapshot identity is content-derived (deterministic)
    snap2 = panel.snapshot("MOM", _dts(SESSIONS[300]))
    assert snap2.snapshot_id == snap.snapshot_id
