"""Agent role migration tests (Phase 4). Deterministic, zero tokens."""
from __future__ import annotations

import pytest

from app.governance.constitution import RESEARCH_OUTPUT_CONTRACT
from app.research import director as DIR
from app.research import falsifier as FALS
from app.research import roles as ROLES
from app.research import specialists as SPEC
from app.research.schema import ExperimentProposal, FalsificationPlan


def _prop(hid, gain, cost):
    return ExperimentProposal(
        hypothesis_id=hid,
        falsification_plan=FalsificationPlan(
            hypothesis_id=hid, tests=["placebo"], kill_criteria=["no lift"],
            max_research_cost=cost),
        dataset="forward-from-2026-10-10", expected_information_gain=gain,
        research_cost=cost, rationale="Falsification-first experiment plan here.")


def test_all_roles_defined_with_contract_and_ban():
    assert set(ROLES.ROLES) == {"factor", "microstructure", "regime_risk",
                                "event_fundamental", "failure_analysis",
                                "director", "falsifier"}
    for role in ROLES.ROLES:
        system, _ = ROLES.build_role_prompt(role, "ctx")
        assert "NEVER emit trade directives" in system
        for key in RESEARCH_OUTPUT_CONTRACT:
            assert key in system, (role, key)
    with pytest.raises(ValueError):
        ROLES.build_role_prompt("day_trader", "ctx")


def test_role_output_validation_rejects_prose_and_directives():
    good = {k: [] for k in RESEARCH_OUTPUT_CONTRACT}
    good["estimated_value"] = 1.0
    assert ROLES.validate_role_output("factor", good) == good
    with pytest.raises(ValueError):
        ROLES.validate_role_output("factor", {"hypotheses": []})
    bad = dict(good, hypotheses=["Buy RELIANCE.NS at the open"])
    with pytest.raises(ValueError):
        ROLES.validate_role_output("factor", bad)


def test_director_prioritizes_gain_per_cost():
    ps = [_prop("H-cheap", 10.0, 1.0), _prop("H-mid", 10.0, 2.0), _prop("H-exp", 30.0, 20.0)]
    assert [p.hypothesis_id for p in DIR.prioritize(ps)] == ["H-cheap", "H-mid", "H-exp"]
    kept, dups = DIR.deduplicate([{"title": "a", "thesis": "b", "claimed_mechanism": "c",
                                   "strategy_family": "veto_filter"},
                                  {"title": "a", "thesis": "b", "claimed_mechanism": "c",
                                   "strategy_family": "veto_filter"}])
    assert len(kept) == 1 and len(dups) == 1


def test_falsifier_menu_and_family_coverage():
    assert "beta-match" in FALS.TEST_MENU and "shuffled-labels" in FALS.TEST_MENU
    for fam in ("ranking", "veto_filter", "risk_filter", "regime_filter", "exit_rule",
                "entry_rule", "universe_filter", "portfolio_weighting",
                "execution_filter", "event_filter", "ensemble_rule"):
        plan = FALS.plan_for(fam)
        assert FALS.check_plan_covers(plan, fam) == []
        assert len(plan["kill_criteria"]) >= 1
    with pytest.raises(ValueError):
        FALS.plan_for("moon_signal")
    with pytest.raises(ValueError):
        FALS.plan_for("ranking", extra=["trust_me"])
    # missing a required test is detected
    assert "beta-match" in FALS.check_plan_covers({"required": []}, "ranking")


def test_specialist_brief_includes_corpse_block():
    from app.research_memory import corpses as CORP
    from app.research_memory import store as ST
    ST.init_tables()
    ST.submit_hypothesis({"hypothesis_id": "TEST-ROLE-H",
                          "title": "TEST-ROLE delivery direction title here",
                          "thesis": "TEST-ROLE delivery percentage predicts direction with "
                                    "enough words to pass the validation length floors.",
                          "economic_reason": "TEST-ROLE rationale with enough words here.",
                          "strategy_family": "veto_filter",
                          "required_features": ["delivery_z"],
                          "claimed_mechanism": "TEST-ROLE mechanism",
                          "falsification_tests": ["placebo"],
                          "novelty_claim": "TEST-ROLE novelty claim here.",
                          "estimated_research_cost": 10.0})
    h = [x for x in ST.list_hypotheses() if x["hypothesis_id"] == "TEST-ROLE-H"][0]
    CORP.bury(h["fp"], {"title": "TEST-ROLE delivery direction",
                        "thesis": "delivery percentage predicts direction",
                        "allowed_reuse": "exhaustion context only"},
              "TEST-ROLE failed", {})
    try:
        brief = SPEC.specialist_brief("microstructure", "delivery predicts direction")
        assert brief["n_corpse_blocks"] >= 1
        assert "MATCHED PRIOR CORPSE" in brief["user"]
        assert "exhaustion context only" in brief["user"]
    finally:
        from app.db import sqlite_conn
        db = sqlite_conn()
        db.execute("DELETE FROM research_hypotheses WHERE hypothesis_id='TEST-ROLE-H'")
        db.execute("DELETE FROM research_corpses WHERE body LIKE '%TEST-ROLE%'")
        db.commit()


def test_legacy_pipeline_preserved_for_archival():
    # Archival direction pipeline must remain importable and behavior-stable;
    # it is RESEARCH_ONLY by type (Phase 1), not deleted (§3).
    from app.agents import manager, debate
    from app.agents import trader_risk as TR
    assert callable(manager.run_manager) and callable(debate.run_debate)
    assert hasattr(TR, "FIXED_BASE_SIZE")
    from app import schemas as S
    d = S.FinalDecision(action="hold", size=0.0, rationale="x" * 20, thesis_version=1)
    assert d.authority == "RESEARCH_ONLY"
