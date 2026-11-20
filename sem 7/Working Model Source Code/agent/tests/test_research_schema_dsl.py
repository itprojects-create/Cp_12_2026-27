"""Research schema + DSL + fingerprints (migration Phase 2). Deterministic."""
from __future__ import annotations

import pytest

from app.research import schema as RS
from app.research import fingerprints as FP
from app.foundry import dsl as DSL


def _hyp(**kw):
    base = dict(hypothesis_id="H-001", title="Delivery exhaustion veto interaction",
                thesis="Blocking new entries when delivery exhaustion coincides with "
                       "elevated volatility may reduce whipsaw entries in low breadth.",
                economic_reason="Exhausted moves revert; entering them pays spread for noise.",
                strategy_family="veto_filter", required_features=["delivery_z", "vix_regime"],
                claimed_mechanism="fade exhausted entries",
                falsification_tests=["leave-regime-out", "placebo threshold"],
                novelty_claim="Conditional interaction, not a standalone signal.",
                estimated_research_cost=25000.0)
    base.update(kw)
    return RS.ResearchHypothesis(**base)


def test_valid_hypothesis_accepted():
    h = _hyp()
    assert h.strategy_family == "veto_filter"
    assert FP.hypothesis_fingerprint(h.model_dump()) .startswith("hyp-")


def test_capital_directives_rejected():
    with pytest.raises(Exception):
        _hyp(thesis="Buy RELIANCE.NS into the close for a quick gain trade idea.")
    with pytest.raises(Exception):
        _hyp(thesis="Place a market order thesis with quantity:=100 shares.")
    with pytest.raises(Exception):
        _hyp(thesis="Use leverage 3x on this factor idea for returns.")
    with pytest.raises(Exception):
        _hyp(thesis="Set portfolio weights: [0.5, 0.5] for the idea.")
    with pytest.raises(Exception):
        _hyp(thesis="Enter at target price Rs 100 with stop-loss at 90.")
    # mechanism prose without directives passes
    h = _hyp(thesis="Momentum pressure persists after surprises; buying pressure "
                    "here means statistical drift pressure, not an instruction.")
    assert h.hypothesis_id == "H-001"


def test_bad_family_and_missing_falsification_rejected():
    with pytest.raises(Exception):
        _hyp(strategy_family="moon_signal")
    with pytest.raises(Exception):
        _hyp(falsification_tests=[])


def test_experiment_priority_ranks_gain_over_cost():
    def prop(gain, cost):
        return RS.ExperimentProposal(
            hypothesis_id="H-001",
            falsification_plan=RS.FalsificationPlan(
                hypothesis_id="H-001", tests=["placebo"], kill_criteria=["no lift"],
                max_research_cost=cost),
            dataset="forward-from-2026-10-10", expected_information_gain=gain,
            research_cost=cost, rationale="Cheap falsification first.")
    assert prop(10.0, 1.0).priority > prop(10.0, 5.0).priority


def test_dsl_rejects_forbidden_ops():
    for bad in ("DIRECT_ORDER", "LEVERAGE_OVERRIDE", "RISK_OVERRIDE",
                "EXECUTE_ARBITRARY_CODE", "NETWORK_ACCESS", "DYNAMIC_EVAL",
                "IMPORT_MODULE", "FILE_WRITE", "SHELL_COMMAND"):
        with pytest.raises(ValueError):
            DSL.compile_program({"ops": [{"op": bad, "params": {}}]})
    with pytest.raises(ValueError):
        DSL.compile_program({"ops": []})


def test_dsl_weight_transform_cannot_upsize():
    with pytest.raises(ValueError):
        DSL.compile_program({"ops": [{"op": "WEIGHT_TRANSFORM", "params": {"mult": 1.5}}]})
    s = DSL.compile_program({"ops": [{"op": "WEIGHT_TRANSFORM", "params": {"mult": 0.5}}]})
    assert s.evaluate_row({})["weight_mult"] == 0.5


def test_dsl_row_semantics():
    s = DSL.compile_program({"ops": [
        {"op": "VETO", "params": {"band_lo": 0.5, "band_hi": 0.75, "veto": 1.0,
                                  "regime": "STRESSED", "breadth": "low"}},
        {"op": "EVENT_BLACKOUT", "params": {"pre": 2, "post": 1}},
    ]})
    hit = {"veto_raw": 0.6, "regime": "STRESSED", "breadth": "low", "blackout": False}
    assert s.evaluate_row(hit)["veto"] == 1.0
    assert s.evaluate_row(hit)["pass"] is True
    miss = dict(hit, regime="CALM")
    assert s.evaluate_row(miss)["veto"] == 0.0
    blocked = dict(hit, blackout=True)
    assert s.evaluate_row(blocked)["pass"] is False
    # missing filter field fails closed (abstention, §25)
    f = DSL.compile_program({"ops": [{"op": "FILTER", "params": {
        "field": "delivery_z", "op": "lt", "value": -2.0}}]})
    assert f.evaluate_row({})["pass"] is False
    assert f.evaluate_row({"delivery_z": -3.0})["pass"] is True


def test_dsl_fingerprints_stable_and_sensitive():
    a = {"ops": [{"op": "VETO", "params": {"band_lo": 0.5, "band_hi": 0.75,
                                           "veto": 1.0}}]}
    b = {"ops": [{"op": "VETO", "params": {"band_lo": 0.5, "band_hi": 0.75,
                                           "veto": 1.0}}]}
    c = {"ops": [{"op": "VETO", "params": {"band_lo": 0.5, "band_hi": 0.75,
                                           "veto": 0.5}}]}
    assert DSL.compile_program(a).fingerprint == DSL.compile_program(b).fingerprint
    assert DSL.compile_program(a).fingerprint != DSL.compile_program(c).fingerprint
    assert FP.parameter_fingerprint({"a": 1}) == FP.parameter_fingerprint({"a": 1})
    assert FP.data_fingerprint("nse", ["B.NS", "A.NS"], "2020", "2021", ["f1"]) == \
        FP.data_fingerprint("nse", ["A.NS", "B.NS"], "2020", "2021", ["f1"])


def test_foundry_proposal_bridge_covers_all_kinds():
    from app.foundry import proposals as P
    veto = P.parse("veto_band_edge", {"band_lo": 0.5, "band_hi": 0.75, "veto": 1.0,
                                      "regime": "STRESSED", "breadth": "low"},
                   rationale="x" * 20)
    topk = P.parse("topK_value", {"K": 30}, rationale="x" * 20)
    black = P.parse("blackout_window", {"pre": 2, "post": 1}, rationale="x" * 20)
    for prop in (veto, topk, black):
        prog = DSL.from_foundry_proposal(prop)
        s = DSL.compile_program(prog)  # must compile — bridge is total
        assert s.fingerprint.startswith("strat-")
    with pytest.raises(ValueError):
        DSL.from_foundry_proposal(type("Q", (), {"kind": "nope", "params": {}})())
