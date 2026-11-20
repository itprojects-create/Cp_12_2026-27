"""LLM-direction honesty fix (prereg_llm_direction_fix.md). Deterministic, no LLM."""
from __future__ import annotations

from app import schemas as S
from app.agents import manager as MGR
from app.agents import trader_risk as TR


def _pm(monkeypatch, action="buy", size=0.08):
    def fake_pm(role, session_id, system, user, schema, fixed=None):
        body = {"action": action, "size": size, "rationale": "mock PM text",
                "thesis_version": 3}
        body.update(fixed or {})
        return schema(**body)
    monkeypatch.setattr(TR, "call_json", fake_pm)


def _thesis(direction="long", mech="OTHER"):
    return S.Thesis(direction=direction, conviction=0.7, key_evidence=["e"],
                    key_risks=["r"], mechanism_type=mech)


def _challenge(status=S.ThesisStatus.HEALTHY):
    return S.Challenge(status=status,
                       core_claim_restated="Mock thesis causal claim restated here",
                       new_evidence_considered=[], duplicate_risks_discarded=["r"],
                       direction_symmetry_check_passed=True, reasons=[])


def _proposal(size_pct=0.08, direction="long"):
    return S.TradeProposal(instrument="T.NS", direction=direction, size_pct=size_pct,
                           entry=100.0, stop=95.0, target=110.0)


def _verdicts():
    return {k: S.RiskVerdict(approve=True, adjusted_size=0.08, notes="ok")
            for k in ("risk_agg", "risk_con", "risk_neu")}


def test_manager_prompt_requires_hold_honesty(monkeypatch):
    captured = {}

    def fake_call(role, session_id, system, user, schema, fixed=None):
        captured["system"] = system
        return S.Thesis(direction="flat", conviction=0.4, key_evidence=["e"],
                        key_risks=["r"], mechanism_type="OTHER")

    monkeypatch.setattr(MGR, "call_json", fake_call)
    rep = S.AnalystReport(agent="technical", summary="flat tape, low conviction signals",
                          signals=[], confidence=0.4, evidence=[])
    MGR.run_manager([rep], [], "test-sid")
    sys = captured["system"]
    assert "0.60" in sys and "falsifier" in sys.lower()
    assert "No-edge honesty is required" in sys
    assert "flat when most analysts are constructive is an error" not in sys


def test_llm_policy_ignores_llm_inflated_size(monkeypatch):
    # PM claims 0.09, proposal 0.02 -> fixed 0.025 either way
    _pm(monkeypatch, size=0.09)
    d1 = TR.run_pm("T.NS", _thesis(), _challenge(), _proposal(size_pct=0.02),
                   _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                   direction_policy="llm")
    _pm(monkeypatch, size=0.02)
    d2 = TR.run_pm("T.NS", _thesis(), _challenge(), _proposal(size_pct=0.08),
                   _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                   direction_policy="llm")
    assert d1.size == 0.025 == d2.size
    assert "CODE SIZING" in d1.rationale


def test_llm_policy_flat_and_broken_still_hold(monkeypatch):
    _pm(monkeypatch)
    flat = TR.run_pm("T.NS", _thesis(direction="flat"), _challenge(), _proposal(),
                     _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                     direction_policy="llm")
    assert flat.action == "hold" and flat.size == 0.0
    broken = TR.run_pm("T.NS", _thesis(), _challenge(S.ThesisStatus.BROKEN), _proposal(),
                       _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                       direction_policy="llm")
    assert broken.action == "hold" and broken.size == 0.0


def test_llm_policy_elevated_halves_fixed_base(monkeypatch):
    _pm(monkeypatch)
    d = TR.run_pm("T.NS", _thesis(mech="MOMENTUM_CONTINUATION"), _challenge(),
                  _proposal(), _verdicts(), 3, "dp", regime="ELEVATED",
                  market_trend="UP", direction_policy="llm")
    assert d.size == 0.0125


def test_llm_policy_countertrend_blocks(monkeypatch):
    _pm(monkeypatch)
    d = TR.run_pm("T.NS", _thesis(direction="long"), _challenge(), _proposal(),
                  _verdicts(), 3, "dp", regime="CALM", market_trend="DOWN",
                  direction_policy="llm")
    assert d.action == "hold" and d.size == 0.0 and "counter-trend" in d.rationale
