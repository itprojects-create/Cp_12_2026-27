"""Champion/challenger + promotion gates (Phase 6). Hermetic via conftest temp DB."""
from __future__ import annotations

import pytest

from app.db import sqlite_conn
from app.evo import champion as CH
from app.evo import promotion as PROM


@pytest.fixture(autouse=True)
def _clean():
    CH.init_tables()
    yield
    db = sqlite_conn()
    db.execute("DELETE FROM strategy_pool WHERE fp LIKE 'TEST-%'")
    db.execute("DELETE FROM champion_history WHERE fp LIKE 'TEST-%'")
    db.commit()


def _evidence(**kw):
    base = {
        "pit_safe": True, "no_leakage_attested": True,
        "dataset": "forward-from-2026-10-10",
        "incremental_alpha": {"n": 120, "estimated_alpha": 0.02,
                              "incremental_sharpe": 0.15, "incremental_maxdd": 0.0,
                              "incremental_cost": 0.001},
        "concentration": {"top_1_share": 0.2},
        "dsr": 0.7, "pbo_lite": "7/8", "placebo": {"p_value": 0.02},
        "stability": {"isolated_peak": False},
        "data_quality": {"verdict": "PASS"},
    }
    base.update(kw)
    return base


def test_v1_pass_and_each_failure_dimension():
    assert PROM.check(_evidence())["eligible"] is True
    cases = [
        ({"pit_safe": False}, "pit_safe"),
        ({"no_leakage_attested": False}, "leakage"),
        ({"dataset": "v1-2023-2024"}, "forward-only"),
        ({"incremental_alpha": {"n": 10, "estimated_alpha": 0.02,
                                "incremental_sharpe": 0.1, "incremental_maxdd": 0.0,
                                "incremental_cost": 0.001}}, "INFANCY"),
        ({"incremental_alpha": {"n": 120, "estimated_alpha": -0.01,
                                "incremental_sharpe": 0.1, "incremental_maxdd": 0.0,
                                "incremental_cost": 0.001}}, "alpha"),
        ({"incremental_alpha": {"n": 120, "estimated_alpha": 0.02,
                                "incremental_sharpe": -0.2, "incremental_maxdd": 0.0,
                                "incremental_cost": 0.001}}, "Sharpe"),
        ({"incremental_alpha": {"n": 120, "estimated_alpha": 0.02,
                                "incremental_sharpe": 0.1, "incremental_maxdd": 0.09,
                                "incremental_cost": 0.001}}, "drawdown"),
        ({"concentration": {"top_1_share": 0.7}}, "lucky-stock"),
        ({"data_quality": {"verdict": "REJECT"}}, "data-quality"),
    ]
    for patch, keyword in cases:
        gate = PROM.check(_evidence(**patch))
        assert gate["eligible"] is False, patch
        assert any(keyword in f for f in gate["failures"]), (patch, gate["failures"])
    # missing statistics warn, missing blocks fail
    assert PROM.check(_evidence(dsr=None))["warnings"]
    assert PROM.check(_evidence(concentration={}))["eligible"] is False
    with pytest.raises(ValueError):
        PROM.check(_evidence(), "GATESET_FUTURE")


def test_genesis_promote_retire_lifecycle():
    g = CH.set_genesis("TEST-GEN", "v4 core", {"blind": "survived 2015-2020"})
    assert g["fp"] == "TEST-GEN" and CH.get_champion()["fp"] == "TEST-GEN"
    assert CH.set_genesis("TEST-GEN2", "other", {})["fp"] == "TEST-GEN"  # idempotent
    CH.register_candidate("TEST-CHAL", "challenger", {}, status="SHADOW")
    assert {c["fp"] for c in CH.list_challengers()} == {"TEST-CHAL"}
    weak = dict(_evidence(), incremental_alpha={"n": 120, "estimated_alpha": -0.01,
                                                "incremental_sharpe": 0.1,
                                                "incremental_maxdd": 0.0,
                                                "incremental_cost": 0.001})
    r1 = CH.promote("TEST-CHAL", weak)
    assert r1["promoted"] is False and CH.get_champion()["fp"] == "TEST-GEN"
    r2 = CH.promote("TEST-CHAL", _evidence())
    assert r2["promoted"] is True and r2["retired"] == "TEST-GEN"
    assert CH.get_champion()["fp"] == "TEST-CHAL"
    assert "TEST-GEN" not in {c["fp"] for c in CH.list_challengers()}
    CH.retire("TEST-CHAL", "forward decay")
    assert CH.get_champion() is None
