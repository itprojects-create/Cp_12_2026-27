"""Day-3 memory + calibration tests (prereg_day3_memory_calibration.md §Gate). Zero tokens."""
import pytest

from app.db import sqlite_conn
from app.memory import layers as L
from app.memory import reflect as R
from app.memory import calibrate as C


@pytest.fixture(autouse=True)
def _clean():
    L.init_tables()
    yield
    db = sqlite_conn()
    db.execute("DELETE FROM mem_events WHERE ref LIKE 'TEST-%'")
    db.execute("DELETE FROM memory_settlements WHERE session_id LIKE 'TEST-%'")
    db.commit()


def _backdate(event_id: int, days: float):
    from datetime import datetime, timedelta, timezone
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sqlite_conn().execute("UPDATE mem_events SET created_at=? WHERE id=?", (ts, event_id))
    sqlite_conn().commit()


def test_layer_validation():
    with pytest.raises(ValueError):
        L.store_event("abyss", "x" * 20, 0.5, ref="TEST-v")
    with pytest.raises(ValueError):
        L.store_event("shallow", "x" * 20, 1.5, ref="TEST-v")
    with pytest.raises(ValueError):
        L.store_event("shallow", "", 0.5, ref="TEST-v")


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def test_decay_recent_beats_old_and_deep_outlasts_shallow():
    new = L.store_event("shallow", "TEST breaker news alpha gamma", 0.5, ref="TEST-d1")
    old = L.store_event("shallow", "TEST breaker news alpha gamma", 0.5, ref="TEST-d2")
    _backdate(old, 30)
    got = {m["id"]: m["score"] for m in L.recall("TEST breaker news", _now())}
    assert got[new] > got[old]
    deep_old = L.store_event("deep", "TEST breaker news alpha gamma", 0.5, ref="TEST-d3")
    shallow_old = L.store_event("shallow", "TEST breaker news alpha gamma", 0.5, ref="TEST-d4")
    _backdate(deep_old, 30)
    _backdate(shallow_old, 30)
    got2 = {m["id"]: m["score"] for m in L.recall("TEST breaker news", _now())}
    assert got2[deep_old] > got2[shallow_old]  # 90d half-life outlasts 5d


def test_recall_pit_and_topk():
    L.store_event("interim", "TEST future leak payload", 1.0, ref="TEST-f",
                  available_at="2099-06-01T00:00:00+00:00")
    L.store_event("interim", "TEST present payload beta", 0.1, ref="TEST-p",
                  available_at="2020-01-01T00:00:00+00:00")
    got = L.recall("TEST payload", "2024-01-01T00:00:00+00:00", k_per_layer=1)
    assert all("future leak" not in m["content"] for m in got)
    assert len([m for m in got if m["layer"] == "interim"]) <= 1


def test_promote_moves_and_resets():
    eid = L.store_event("shallow", "TEST promote me alpha", 0.9, ref="TEST-pr")
    _backdate(eid, 60)
    before = {m["id"]: m["score"] for m in L.recall("TEST promote", _now())}
    assert L.promote(eid) == "interim"
    after = {m["id"]: m["score"] for m in L.recall("TEST promote", _now())}
    assert after[eid] > before[eid]  # recency reset
    assert L.promote(eid) == "deep"
    assert L.promote(eid) == "deep"  # terminal layer sticks
    with pytest.raises(ValueError):
        L.promote(999999999)


def test_pava_monotone_and_brier_improves():
    xs = [i / 20 for i in range(21) for _ in (0, 1)]
    pairs = [(x, 1 if x > 0.5 else 0) for x in xs]
    m = C.pava_fit(pairs)
    assert m["trained"] is True
    assert all(b >= a for a, b in zip(m["ys"], m["ys"][1:]))  # monotone
    raw_brier = C.brier(pairs, [0.5] * len(pairs))
    cal_brier = C.brier(pairs, [C.predict(m, x) for x, _ in pairs])
    assert cal_brier < raw_brier
    assert C.pava_fit([]) == {"xs": [], "ys": [], "trained": False}


def test_identity_fallback_below_threshold():
    assert C.predict({"trained": False}, 0.7) == pytest.approx(0.7)
    assert C.predict({"trained": False}, 9.0) == 1.0  # clamped even in fallback
    assert C.MIN_LABELED_ROWS == 50


def test_whipsaw_label_cost_boundary():
    # cost = size * 0.0021: dust gain 0.0001 on size 0.10 -> 0.0001-0.00021 < 0
    assert R.whipsaw_label(0.0001, 0.10) == 1
    assert R.whipsaw_label(-0.01, 0.0) == 1
    assert R.whipsaw_label(0.10, 0.10) == 0
    assert R.whipsaw_label(0.0, None) == 0  # exactly flat is not a whipsaw


def test_kelly_bounds_adversarial():
    assert C.kelly_fraction(0.0, 2.0, 1.0) == 0.0
    assert C.kelly_fraction(1.0, 100.0, 0.01) <= 1.0
    assert C.kelly_fraction(0.7, 1.0, 0.0) == pytest.approx(0.5)  # no losses: capped
    assert C.kelly_fraction(1.5, 1.0, 1.0) == 0.0  # invalid p
    assert C.kelly_fraction(0.6, -1.0, 1.0) == 0.0


def test_apply_sizing_never_exceeds_core():
    cal = {"xs": [0.0, 0.6], "ys": [0.1, 0.9], "trained": True}
    for core in (0.0, 0.05, 0.10):
        for raw in (-1.0, 0.0, 0.3, 0.8, 2.0):
            r = C.apply_sizing(core, raw, cal, 0.06, 0.04)
            assert 0.0 <= r["size"] <= core
            assert 0.0 <= r["veto"] <= 1.0
    # Kelly gate: hopeless expectation -> full veto regardless of map
    r = C.apply_sizing(0.10, 0.0, {"xs": [0.0], "ys": [0.99], "trained": True}, 0.01, 0.10)
    assert r["veto"] == 1.0 and r["size"] == 0.0 and r["gated"] is True


def _seed_settlements():
    db = sqlite_conn()
    rows = [
        ("TEST-S1", "AAA.NS", "2024-01-05", 0.06, 0.30, "CALM", 0.6, 0.08),
        ("TEST-S2", "AAA.NS", "2024-02-05", -0.08, 0.70, "CALM", 0.6, 0.08),
        ("TEST-S3", "BBB.NS", "2024-03-05", 0.03, 0.60, "STRESSED", 0.3, 0.05),
    ]
    for sid, t, d, raw, veto, reg, br, sz in rows:
        db.execute(
            "INSERT OR REPLACE INTO memory_settlements(session_id, ticker, trade_date, raw_ret,"
            " alpha_ret, holding_days, resolved_at, reflection, veto, regime, breadth, size)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, t, d, raw, raw, 20, "2024-06-01T00:00:00+00:00", f"TEST note {sid}",
             veto, reg, br, sz))
    db.commit()


def test_reflection_over_synthetic_settlements():
    _seed_settlements()
    mr = R.market_reflection("2025-01-01T00:00:00+00:00", "CALM")
    assert "veto [0.25,0.50) under CALM: whipsaw 0/1" in mr
    assert "veto [0.50,0.75) under CALM: whipsaw 1/1" in mr
    dr = R.decision_reflection("AAA.NS", "2025-01-01T00:00:00+00:00")
    assert "WHIPSAW" in dr and "held" in dr
    assert "no settled" in R.market_reflection("2020-01-01T00:00:00+00:00")
    ctx = R.build_veto_context("AAA.NS", "2025-01-01T00:00:00+00:00", "CALM", 0.55)
    assert "Veto context" in ctx and "Recalled memory" in ctx and "reflection" in ctx.lower()


def test_load_labeled_pit_filter():
    _seed_settlements()
    all_rows = C.load_labeled()
    assert len(all_rows) >= 3
    early = C.load_labeled("2024-01-01T00:00:00+00:00")
    assert all_rows and early == []
    labels = dict()
    for v, y in all_rows:
        labels[v] = y
    assert labels[0.70] == 1 and labels[0.30] == 0
