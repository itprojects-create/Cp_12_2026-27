"""Governance migration Phase 1: constitution, boundaries, safe defaults.

Deterministic, zero tokens, zero network.
"""
from __future__ import annotations

import pytest

from app.governance import constitution as C


def test_constitution_has_15_rules():
    assert len(C.RULES) == 15
    assert [r["id"] for r in C.RULES] == [f"R{i}" for i in range(1, 16)]
    assert all(r["statement"] and r["enforced_by"] for r in C.RULES)


def test_gateset_matches_frozen_gates():
    from app.eval import gates as G
    frozen = C.GATESETS[C.Gateset.FROZEN_20260918]
    assert frozen["min_decisive"] == G.MIN_DECISIVE
    assert frozen["accuracy_min"] == G.ACCURACY_MIN
    assert frozen["no_edge_hold_min"] == G.NO_EDGE_HOLD_MIN
    assert frozen["trade_rate_lo"] == G.TRADE_RATE_LO
    assert frozen["trade_rate_hi"] == G.TRADE_RATE_HI


def test_dataset_registry_burn_and_forward():
    assert C.dataset_status("v1-2023-2024") == C.DatasetStatus.BURNED
    assert C.dataset_status("backtest-2021-2026") == C.DatasetStatus.BURNED
    assert C.dataset_status("forward-from-2026-10-10") == C.DatasetStatus.FORWARD_ONLY
    assert C.promotion_eligible_dataset("forward-from-2026-10-10") is True
    assert C.promotion_eligible_dataset("v1-2023-2024") is False
    # unknown datasets are exploratory, never assumed clean
    assert C.dataset_status("something-new-2027") == C.DatasetStatus.EXPLORATORY
    assert C.promotion_eligible_dataset("something-new-2027") is False


def test_status_labels_guard_promotion_claims():
    with pytest.raises(ValueError):
        C.describe("BACKTEST_POSITIVE", "strategy is profitable and validated")
    with pytest.raises(ValueError):
        C.describe("HISTORICALLY_SURVIVED", "deployment-ready alpha generating system")
    # champion carries forward evidence; plain factual text always passes
    assert C.describe("CHAMPION", "promoted 2026-11-01 on forward evidence") is not None
    assert C.describe("BACKTEST_ONLY", "CAGR +12% after costs, MaxDD 9%") is not None


def test_research_output_contract():
    assert C.check_research_output({k: None for k in C.RESEARCH_OUTPUT_CONTRACT}) == []
    missing = C.check_research_output({"hypotheses": []})
    assert "falsification_plan" in missing and "estimated_value" in missing
    assert len(C.check_research_output("prose only")) == len(C.RESEARCH_OUTPUT_CONTRACT)


def test_final_decision_is_research_only_by_type():
    from app import schemas as S
    d = S.FinalDecision(action="buy", size=0.025, rationale="x" * 20, thesis_version=1)
    assert d.authority == "RESEARCH_ONLY"
    assert d.cannot_create_position and d.cannot_reverse_position
    assert d.cannot_increase_exposure
    assert C.assert_research_only(d) is d
    # legacy / hand-built objects without the literals fail closed
    class Legacy:
        action = "buy"
    with pytest.raises(ValueError):
        C.assert_research_only(Legacy())
    with pytest.raises(ValueError):
        C.assert_research_only(object())


def test_config_safe_defaults():
    from app.config import settings
    assert settings.LLM_MONEY_AUTHORITY is False
    assert settings.LLM_DIRECTION_AUTHORITY is False
    assert settings.LLM_OVERLAY_ENABLED is False
    assert settings.RESEARCH_AGENT_ENABLED is True
    assert settings.RESEARCH_FOUNDRY_ENABLED is True
    assert settings.RESEARCH_MEMORY_ENABLED is True
    assert settings.FALSIFICATION_REQUIRED is True
    assert settings.PIT_REQUIRED_FOR_PROMOTION is True
    assert settings.FORWARD_REQUIRED_FOR_PROMOTION is True


def test_overlay_off_is_no_llm_control():
    from app.core.overlay import apply_llm_overlay
    core = {"A.NS": 0.05, "B.NS": 0.03}
    views = {"A.NS": {"action": "sell", "size": 0.05, "core_direction": "long"}}
    finals, rep = apply_llm_overlay(core, views, enabled=False)
    assert finals == core and rep["overlay"] == "off"
    assert rep["n_vetoed"] == 0 and rep["n_untouched"] == 2


def test_overlay_on_requires_tag_and_only_shrinks():
    from app.core.overlay import apply_llm_overlay
    core = {"A.NS": 0.05, "B.NS": 0.04, "C.NS": 0.02}
    views = {"A.NS": {"action": "sell", "size": 0.05, "core_direction": "long"},
             "B.NS": {"action": "buy", "size": 0.01, "core_direction": "long"}}
    with pytest.raises(ValueError):
        apply_llm_overlay(core, views, enabled=True)
    finals, rep = apply_llm_overlay(core, views, enabled=True, experimental_tag="w2-ablation-C")
    assert finals["A.NS"] == 0.0  # opposite = veto, never flip
    assert finals["B.NS"] == 0.01  # agree = resize down
    assert finals["C.NS"] == 0.02  # no view = core stands
    assert all(v <= core[k] + 1e-12 for k, v in finals.items())
    assert rep["tag"] == "w2-ablation-C"


def test_overlay_default_follows_config_flag():
    from app.core.overlay import apply_llm_overlay
    from app.config import settings
    assert settings.LLM_OVERLAY_ENABLED is False
    finals, rep = apply_llm_overlay({"A.NS": 0.05}, {})
    assert finals == {"A.NS": 0.05} and rep["overlay"] == "off"


def test_research_has_no_broker_order_capability():
    import pathlib
    for pkg in ("app/agents", "app/foundry", "app/governance"):
        for p in pathlib.Path(pkg).glob("*.py"):
            src = p.read_text(encoding="utf-8")
            assert "SmartConnect" not in src, p.name
            assert "place_order" not in src and "create_order" not in src, p.name
    from app.data import broker_angel as B
    assert not any("order" in n.lower() for n in dir(B) if not n.startswith("_"))
    with pytest.raises(Exception):
        B.fetch_portfolio()  # stubbed/NotConfigured without creds


def test_confidence_never_maps_to_size():
    # §38: thesis conviction must not control money. LLM policy size is the
    # fixed code constant regardless of conviction.
    from app.agents import trader_risk as TR
    from app import schemas as S

    def fake_pm(role, session_id, system, user, schema, fixed=None):
        body = {"action": "buy", "size": 0.09, "rationale": "mock PM text",
                "thesis_version": 3}
        body.update(fixed or {})
        return schema(**body)

    orig = TR.call_json
    TR.call_json = fake_pm
    try:
        for conviction in (0.05, 0.5, 0.99):
            thesis = S.Thesis(direction="long", conviction=conviction,
                              key_evidence=["e"], key_risks=["r"],
                              mechanism_type=S.MechanismType.OTHER)
            challenge = S.Challenge(
                status=S.ThesisStatus.HEALTHY,
                core_claim_restated="Mock thesis causal claim restated here",
                new_evidence_considered=[], duplicate_risks_discarded=[],
                direction_symmetry_check_passed=True, reasons=[])
            proposal = S.TradeProposal(instrument="T.NS", direction="long",
                                       size_pct=0.08, entry=100.0, stop=95.0,
                                       target=110.0)
            verdicts = {k: S.RiskVerdict(approve=True, adjusted_size=0.08, notes="ok")
                        for k in ("risk_agg", "risk_con", "risk_neu")}
            d = TR.run_pm("T.NS", thesis, challenge, proposal, verdicts, 3, "gov",
                          regime="CALM", market_trend="UP", direction_policy="llm")
            assert d.size == TR.FIXED_BASE_SIZE, conviction
            assert C.assert_research_only(d) is d
    finally:
        TR.call_json = orig
