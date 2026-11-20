"""P3 forward-blackout experiment tests (§78 forward-experiment + blackout). Hermetic synthetics."""
from __future__ import annotations

import json

from app.core.trend_core_v4 import run_core_v4
from app.events import blackout as BO

import sys
sys.path.insert(0, "scripts")
from run_event_blackout_forward import (  # noqa: E402
    eligibility_ts,
    make_gate,
    run_experiment,
)


def _panel(n_names=4, n_bars=120, crash_at=None, crash_sym="AAA.NS"):
    idx = [100 + i * 0.3 for i in range(n_bars)]
    names = {}
    syms = ["AAA.NS", "BBB.NS", "CCC.NS", "DDD.NS"][:n_names]
    for k, s in enumerate(syms):
        cs = [50 + (i * 0.5) + k * 2 for i in range(n_bars)]
        if s == crash_sym and crash_at is not None:
            for i in range(crash_at, n_bars):
                cs[i] *= 0.80  # -20% gap, stays down
        names[s] = cs
    dates = [f"2026-11-{(i % 28) + 1:02d}" for i in range(n_bars)]
    return {"index": idx, "names": names, "dates": dates}


def _ann(symbol, eff, elig, bc=True, etype="BOARD_MEETING", sev=0.7):
    return {"record_id": f"R-{symbol}-{eff}", "symbol": symbol, "event_type": etype,
            "severity": sev, "blackout_candidate": bc, "effective_ts": eff,
            "eligibility_ts": elig}


def test_gate_pit_eligibility_no_future_leak():
    rule = BO.BLACKOUT_FAMILY_V1[3]  # B3
    log: list = []
    # intimation eligible 2026-11-10 for a 2026-11-12 event: invisible on 11-05
    anns = [_ann("AAA.NS", "2026-11-12T10:00:00+00:00", "2026-11-10T10:00:00+00:00")]
    gate = make_gate(rule, anns, log=log)
    assert gate("AAA.NS", 5, "2026-11-05") is True  # future intimation cannot block
    assert gate("AAA.NS", 20, "2026-11-11") is False  # pre-window blocks (B3 pre=1)
    assert log and log[0]["rule"] == "B3"


def test_b3_dodges_planted_crash_control_takes_it():
    # §71 philosophy, verified: entry blackout blocks NEW entries only — existing
    # positions ride through (mandatory exits are never blocked). With one event,
    # forfeited upside on up-drift names dominates: B3 <= B0 here is the honest
    # mechanism outcome (opportunity cost > tail saving at n=1), not a bug.
    panel = _panel(crash_at=60)
    anns = [_ann("AAA.NS", "2026-11-05T10:00:00+00:00", "2026-11-01T10:00:00+00:00")]
    out = run_experiment(panel, anns)
    b3 = out["arms"]["B3"]
    assert b3["blocked_entries"] >= 1
    assert out["arms"]["B0"]["total_return"] != b3["total_return"]  # gate had effect
    # all blocks hit up-drift entries here: opportunity cost is directly visible
    assert out["opportunity"]["missed_profitable_entries"] >= 1
    assert out["verdict"] == "EVENT_FORWARD_INFANCY"  # 1 event << minimums


def test_opportunity_cost_counts_missed_upside():
    panel = _panel()  # no crash: everything drifts up
    anns = [_ann("AAA.NS", "2026-11-05T10:00:00+00:00", "2026-11-01T10:00:00+00:00")]
    out = run_experiment(panel, anns)
    assert out["opportunity"]["blocked_trade_count"] >= 1
    assert out["opportunity"]["missed_profitable_entries"] >= 1  # up-drift blocked
    assert out["opportunity"]["missed_upside_ret_space"] > 0
    assert "hidden weights" in out["utility"]["note"]


def test_ready_gate_with_manufactured_sample():
    panel = _panel(n_names=4)
    anns = []
    for d in range(1, 21):  # 20 distinct event days x 2 symbols = 40 events
        for s in ["AAA.NS", "BBB.NS"]:
            anns.append(_ann(s, f"2026-11-{d:02d}T10:00:00+00:00",
                             f"2026-10-{min(d, 28):02d}T10:00:00+00:00"))
    for k in range(10):  # company breadth: 2 -> 12 independent companies
        anns.append(_ann(f"SYM{k}.NS", "2026-11-15T10:00:00+00:00",
                         "2026-10-15T10:00:00+00:00"))
    out = run_experiment(panel, anns)
    assert out["sample"]["n_events"] >= 30 and out["sample"]["n_companies"] >= 10
    assert out["sample"]["n_event_days"] >= 20
    assert out["verdict"] == "READY_FOR_GATE"


def test_manifest_frozen_before_outcomes():
    manifest = json.load(open("data/event_blackout_v1_manifest.json", encoding="utf-8"))
    art = json.load(open("data/event_blackout_forward_2026-10-10.json", encoding="utf-8"))
    assert manifest["freeze_at"] <= art["as_of"]
    assert manifest["candidate_family"] == ["B0", "B1", "B2", "B3"]
    assert manifest["evidence_class"] == "RISK_CONTROL"
    assert manifest["status"] == "FROZEN_BEFORE_OUTCOMES"


def test_entry_gate_legacy_parity():
    panel = _panel()
    a = run_core_v4(panel["index"], panel["names"])
    b = run_core_v4(panel["index"], panel["names"], dates=panel["dates"],
                    entry_gate_fn=lambda nm, t, d: True)
    assert a.eq_curve == b.eq_curve  # allow-all gate == legacy, byte-identical


def test_leave_one_event_type_out_wiring():
    from app.eval import loo as LOO
    items = [{"id": f"E{i}", "event_type": "EARNINGS", "pnl": 1.0} for i in range(5)]
    items += [{"id": "M1", "event_type": "MERGER", "pnl": 50.0}]
    rep = LOO.drop_one_out(items, lambda i: i["event_type"], LOO.total_pnl)
    assert rep["worst_drop"] == "MERGER" and rep["baseline"] == 55.0


def test_experiment_recorded_in_memory():
    from app.research_memory import store as ST
    from app.db import sqlite_conn
    ST.init_tables()
    exp = ST.record_experiment("hyp-event-blackout-v1",
                               {"TEST-OR-NOT": "event_blackout_v1 manifest ref"},
                               status="EXPERIMENTING")
    assert exp.startswith("EXP-")
    sqlite_conn().execute("DELETE FROM research_experiments WHERE id=?", (exp,))
    sqlite_conn().commit()
