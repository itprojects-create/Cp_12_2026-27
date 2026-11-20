"""Trend direction policy (H1) + v4 blind-set tests. Deterministic, no LLM."""
from __future__ import annotations

from app import schemas as S
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


def _pm_trend(monkeypatch, **kw):
    _pm(monkeypatch)
    return TR.run_pm("T.NS", kw.get("thesis", _thesis()),
                     kw.get("challenge", _challenge()), kw.get("proposal", _proposal()),
                     _verdicts(), 3, "dp", regime=kw.get("regime", "CALM"),
                     market_trend=kw.get("market_trend", "UP"), direction_policy="trend")


def test_trend_up_goes_long_and_down_goes_short(monkeypatch):
    up = _pm_trend(monkeypatch, market_trend="UP")
    assert up.action == "buy" and up.size == 0.08 and "index trend UP" in up.rationale
    dn = _pm_trend(monkeypatch, market_trend="DOWN")
    assert dn.action == "sell" and dn.size == 0.08 and "index trend DOWN" in dn.rationale


def test_trend_range_or_unknown_holds(monkeypatch):
    for tr in ("RANGE", "UNKNOWN", None):
        d = _pm_trend(monkeypatch, market_trend=tr)
        assert d.action == "hold" and d.size == 0.0 and "no edge" in d.rationale


def test_trend_policy_vetoes_flat_and_broken(monkeypatch):
    flat = _pm_trend(monkeypatch, thesis=_thesis(direction="flat"), market_trend="UP")
    assert flat.action == "hold" and flat.size == 0.0 and "flat thesis" in flat.rationale
    broken = _pm_trend(monkeypatch, challenge=_challenge(S.ThesisStatus.BROKEN),
                       market_trend="UP")
    assert broken.action == "hold" and broken.size == 0.0 and "BROKEN" in broken.rationale


def test_trend_size_is_fixed_not_llm_inflated(monkeypatch):
    # PM claims 0.09; policy uses the proposal size, capped at 0.10, never PM's number
    _pm(monkeypatch, size=0.09)
    d = TR.run_pm("T.NS", _thesis(), _challenge(), _proposal(size_pct=0.02),
                  _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                  direction_policy="trend")
    assert d.size == 0.02
    # zero proposal size -> deterministic 0.03 default
    d2 = TR.run_pm("T.NS", _thesis(), _challenge(), _proposal(size_pct=0.0),
                   _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                   direction_policy="trend")
    assert d2.size == 0.03


def test_llm_policy_default_unchanged_by_new_param(monkeypatch):
    # m11 (prereg_llm_direction_fix.md F2): LLM never sizes — fixed 0.025 base,
    # audit tag always present. Direction still from dec.action/thesis.
    _pm(monkeypatch)
    d = TR.run_pm("T.NS", _thesis(), _challenge(), _proposal(),
                  _verdicts(), 3, "dp", regime="CALM", market_trend="UP",
                  direction_policy="llm")
    assert d.action == "buy" and d.size == 0.025 and "CODE SIZING" in d.rationale


def test_v4_set_disjoint_from_all_prior():
    from app.eval.scenarios import SCENARIOS as V1
    from app.eval.scenarios_v5 import SCENARIOS_V5
    from app.eval.scenarios_v3rd import SCENARIOS_V3RD
    from app.eval.scenarios_v4 import SCENARIOS_V4, SET_NAME
    assert SET_NAME == "v4-2022-blind" and len(SCENARIOS_V4) == 24
    assert not (set(SCENARIOS_V4) & set(V1))
    assert not (set(SCENARIOS_V4) & set(SCENARIOS_V5))
    assert not (set(SCENARIOS_V4) & set(SCENARIOS_V3RD))
