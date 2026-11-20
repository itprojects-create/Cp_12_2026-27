"""Evidence-class gates tests (P4, §78 evidence-class block). Hermetic."""
from __future__ import annotations

import pytest

from app.evo import champion as CH
from app.evo import evidence_gates as EG
from app.db import sqlite_conn


@pytest.fixture(autouse=True)
def _clean():
    CH.init_tables()
    yield
    db = sqlite_conn()
    db.execute("DELETE FROM strategy_pool WHERE fp LIKE 'TEST-%'")
    db.execute("DELETE FROM champion_history WHERE fp LIKE 'TEST-%'")
    db.commit()


def _risk(**kw):
    base = {"pit_safe": True, "no_leakage_attested": True,
            "dataset": "forward-from-2026-10-10",
            "sample": {"n_events": 40, "n_companies": 12, "n_event_days": 22},
            "risk": {"candidate_cvar95": -0.008, "control_cvar95": -0.012,
                     "candidate_maxdd": 0.10, "control_maxdd": 0.11,
                     "opportunity_drag": 0.005, "added_cost": 0.001,
                     "candidate_max_event_loss": -0.03,
                     "control_max_event_loss": -0.06},
            "data_quality": {"verdict": "PASS"}}
    base.update(kw)
    return base


def test_risk_pass_despite_lower_cagr():
    # §32: a risk control is NOT rejected solely for lower CAGR — tail wins.
    gate = EG.check_risk(_risk())
    assert gate["eligible"] is True and gate["verdict"] == "RISK_PASS"


def test_risk_failure_dimensions():
    assert EG.check_risk(_risk(pit_safe=False))["eligible"] is False
    assert EG.check_risk(_risk(dataset="v1-2023-2024"))["eligible"] is False
    small = _risk(sample={"n_events": 5, "n_companies": 2, "n_event_days": 3})
    g = EG.check_risk(small)
    assert g["eligible"] is False and g["verdict"] == "FORWARD_PENDING"
    no_tail = _risk(risk={**_risk()["risk"], "candidate_cvar95": -0.012})
    assert any("tail" in f for f in EG.check_risk(no_tail)["failures"])
    worse_cat = _risk(risk={**_risk()["risk"],
                            "candidate_max_event_loss": -0.09})
    assert any("catastrophic" in f for f in EG.check_risk(worse_cat)["failures"])
    pricey = _risk(risk={**_risk()["risk"], "opportunity_drag": 0.05})
    assert any("drag" in f for f in EG.check_risk(pricey)["failures"])
    bad_dq = _risk(data_quality={"verdict": "REJECT"})
    assert EG.check_risk(bad_dq)["eligible"] is False  # §87
    with pytest.raises(ValueError):
        EG.check_risk(_risk(), "RISK_FUTURE")


def test_execution_and_quality_gates():
    exe = {"pit_safe": True, "dataset": "forward-from-2026-10-10",
           "execution": {"n": 120, "cost_improvement": 0.002,
                         "turnover_reduction": 0.01, "strategy_degradation": -0.001}}
    assert EG.check_execution(exe)["verdict"] == "EXECUTION_PASS"
    assert EG.check_execution({**exe, "execution": {"n": 10}})["verdict"] == "FORWARD_PENDING"
    bad = dict(exe, execution={"n": 120, "cost_improvement": 0.0,
                               "turnover_reduction": 0.0, "strategy_degradation": 0.0})
    assert EG.check_execution(bad)["eligible"] is False
    q = {"data_quality_delta": {"coverage_delta": 0.1, "pit_confidence_delta": 0.2,
                                "mismatch_rate": 0}}
    assert EG.check_quality(q)["verdict"] == "QUALITY_PASS"
    assert EG.check_quality({})["verdict"] == "INSUFFICIENT_DATA"
    assert EG.check_quality({"data_quality_delta": {"coverage_delta": 0.0,
                                                    "pit_confidence_delta": 0.1,
                                                    "mismatch_rate": 0}})["eligible"] is False
    with pytest.raises(ValueError):
        EG.check_by_class("VIBES", {})


def test_dispatch_alpha_unchanged_and_auto_promote():
    # ALPHA path reuses frozen V1 behavior (unweakened).
    from app.evo import promotion as PROM
    ev = {"pit_safe": True, "no_leakage_attested": True,
          "dataset": "forward-from-2026-10-10",
          "incremental_alpha": {"n": 120, "estimated_alpha": 0.02,
                                "incremental_sharpe": 0.1, "incremental_maxdd": 0.0,
                                "incremental_cost": 0.001},
          "concentration": {"top_1_share": 0.2}}
    assert EG.check_by_class("ALPHA", ev)["verdict"] == "ALPHA_PASS"
    # risk-only improvement cannot pass the alpha gate ...
    risk_only = {"pit_safe": True, "no_leakage_attested": True,
                 "dataset": "forward-from-2026-10-10",
                 "incremental_alpha": {"n": 120, "estimated_alpha": -0.005,
                                       "incremental_sharpe": 0.05, "incremental_maxdd": -0.01,
                                       "incremental_cost": 0.001},
                 "concentration": {"top_1_share": 0.2}}
    assert EG.check_by_class("ALPHA", risk_only)["eligible"] is False
    # ... but the same economics under RISK_CONTROL are judged on tail, not CAGR.
    CH.set_genesis("TEST-P4-GEN", "gen", {})
    CH.register_candidate("TEST-P4-RISK", "blackout-b3", {}, status="SHADOW")
    r = CH.promote("TEST-P4-RISK", {**_risk(), "evidence_class": "RISK_CONTROL"},
                   gateset="auto")
    assert r["promoted"] is True and r["verdict"] == "RISK_PASS"
    assert CH.get_champion()["fp"] == "TEST-P4-RISK"
