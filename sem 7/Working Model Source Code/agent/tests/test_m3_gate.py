"""M3 gate regression tests: deterministic, code-level, no LLM involved.

STRESSED+MOMENTUM must force hold/size-0 no matter what PM/Trader/Risk said;
CALM+MOMENTUM and STRESSED+MEAN_REVERSION must pass through untouched.
"""
from __future__ import annotations
import json

from app import schemas as S
from app.agents import trader_risk as TR


def _pm_buy(monkeypatch):
    def fake_pm(role, session_id, system, user, schema, fixed=None):
        assert role == "portfolio_manager"
        body = {"action": "buy", "size": 0.08, "rationale": "mock PM approval text",
                "thesis_version": 3}
        body.update(fixed or {})
        return schema(**body)
    monkeypatch.setattr(TR, "call_json", fake_pm)


def _thesis(mech: str) -> S.Thesis:
    return S.Thesis(direction="long", conviction=0.7, key_evidence=["e1"],
                    key_risks=["r1"], mechanism_type=mech)


def _healthy() -> S.Challenge:
    return S.Challenge(status=S.ThesisStatus.HEALTHY,
                       core_claim_restated="Mock thesis causal claim restated here",
                       new_evidence_considered=[],
                       duplicate_risks_discarded=["r1"],
                       direction_symmetry_check_passed=True, reasons=[])


def _proposal() -> S.TradeProposal:
    return S.TradeProposal(instrument="T.NS", direction="long", size_pct=0.08,
                           entry=100.0, stop=95.0, target=110.0)


def _verdicts() -> dict:
    return {k: S.RiskVerdict(approve=True, adjusted_size=0.08, notes="ok")
            for k in ("risk_agg", "risk_con", "risk_neu")}


def test_stressed_momentum_forced_hold(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("MOMENTUM_CONTINUATION"), _healthy(),
                    _proposal(), _verdicts(), 3, "m3t1", regime="STRESSED")
    assert dec.action == "hold" and dec.size == 0.0
    assert "CODE GUARDRAIL" in dec.rationale and "STRESSED" in dec.rationale


def test_calm_momentum_passthrough(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("MOMENTUM_CONTINUATION"), _healthy(),
                    _proposal(), _verdicts(), 3, "m3t2", regime="CALM")
    assert dec.action == "buy" and dec.size == 0.025  # m11 fixed base (LLM size ignored)
    assert "CODE GUARDRAIL" not in dec.rationale


def test_stressed_mean_reversion_unaffected(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("MEAN_REVERSION"), _healthy(),
                    _proposal(), _verdicts(), 3, "m3t3", regime="STRESSED")
    assert dec.action == "buy" and dec.size == 0.025  # m11 fixed base
    assert "CODE GUARDRAIL" not in dec.rationale


def test_elevated_momentum_halved_with_tag(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("MOMENTUM_CONTINUATION"), _healthy(),
                    _proposal(), _verdicts(), 3, "m3t4", regime="ELEVATED")
    assert dec.action == "buy" and dec.size == 0.0125  # 0.025 halved
    assert "CODE GUARDRAIL" in dec.rationale and "ELEVATED" in dec.rationale


def test_unknown_regime_never_gates(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("MOMENTUM_CONTINUATION"), _healthy(),
                    _proposal(), _verdicts(), 3, "m3t5", regime=None)
    assert dec.action == "buy" and dec.size == 0.025  # m11 fixed base


def test_manager_prompt_mandates_mechanism():
    from app.agents.manager import run_manager  # noqa: F401 (import = module loads)
    import app.agents.manager as M
    import inspect
    src = inspect.getsource(M.run_manager)
    assert "mechanism_type" in src and "MOMENTUM_CONTINUATION" in src


def test_pre_m3_thesis_payload_still_validates():
    # Backward compat: v5.1 checkpoints without the field load as OTHER (never gated).
    old = {"direction": "long", "conviction": 0.6,
           "key_evidence": ["e1"], "key_risks": ["r1"]}
    t = S.Thesis(**old)
    assert t.mechanism_type == S.MechanismType.OTHER
    assert json.loads(t.model_dump_json())["mechanism_type"] == "OTHER"
