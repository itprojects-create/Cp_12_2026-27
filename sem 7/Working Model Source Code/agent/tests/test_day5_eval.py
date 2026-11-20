"""Day-5 biting-eval tests (prereg_day5_eval.md Gate). Deterministic, zero tokens."""
import json
import os

from app.eval import dsr as D
from app.eval import friction as F
from app.eval import perturb as PZ


def test_trial_registry_complete():
    assert D.K == 12  # 10 design-window + 2 blind 2015-2020 (prereg_blind_2015_2020.md)
    for name, sr, artifact in D.TRIALS:
        assert name and artifact and sr > 0
    blinds = [t for t in D.TRIALS if t[0].startswith("blind-")]
    assert len(blinds) == 2 and all("2015-01-01_2020-12-31" in t[2] for t in blinds)


def test_dsr_math():
    assert D.Phi(0.0) == 0.5
    assert abs(D.phi_inv(0.5)) < 1e-6
    r = D.dsr(0.0, 1420, 0.0, 3.0, [0.5, 0.6])
    assert r["dsr"] < 0.5  # zero SR vs positive null expectation -> below coin flip
    sr0 = D.expected_sr_null([0.5, 0.6])
    assert D.dsr(sr0, 1420, 0.0, 3.0, [0.5, 0.6])["dsr"] == 0.5  # SR == null -> coin flip
    assert D.dsr(5.0, 1420, 0.0, 3.0, [0.5, 0.6])["dsr"] > 0.99  # overwhelming edge survives
    low_k = D.dsr(0.8, 252, 0.5, 4.0, [0.8, 0.2])
    high_k = D.dsr(0.8, 252, 0.5, 4.0, [0.8, 0.2] * 25)  # same variance, K=50
    assert high_k["sr0_null"] > low_k["sr0_null"]  # more trials -> higher null bar
    assert low_k["dsr"] > high_k["dsr"]  # ...which haircuts the same SR harder
    assert high_k["trials"] == 50
    neg = D.dsr(-0.5, 1420, 0.0, 3.0, [0.2, 0.3])
    assert neg["dsr"] < 0.5


def test_perturb_control_and_veto():
    const = lambda row: 0.7
    grid = [{"a": 1.0, "b": 2.0} for _ in range(10)]
    c = PZ.suite(const, grid)
    assert c["PC"] == 1.0 and c["IDS"] == 0.0  # validity check: constant flagged
    assert c["ids_gate"] is False
    from app.core.overlay import veto_fraction
    rows = [{"ret_5d": -10 + i, "dist_hi": -10 + i, "blackout": False} for i in range(30)]
    fn = PZ.veto_row_fn(veto_fraction, "ELEVATED", 0.35)
    v = PZ.suite(fn, rows)
    assert 0.0 <= v["PC"] <= 1.0 and v["IDS"] > 0  # genuinely input-driven
    assert 0.0 <= v["CI"] <= 1.0
    # mixed-regime grid: table discriminates (fires sometimes, Amendment 1 gate)
    mixed = [{"ret_5d": -10 + i * 0.8, "dist_hi": -15 + i * 0.6,
              "regime": ["CALM", "ELEVATED", "STRESSED"][i % 3]} for i in range(40)]
    m = PZ.suite(lambda r: veto_fraction(r["regime"], 0.35, r["ret_5d"], r["dist_hi"]), mixed)
    assert m["pc_gate"] is True and m["nondegenerate"] is True
    # STRESSED + narrow breadth is a preregistered BLANKET block: stable (PC passes),
    # fires everywhere by design — documented here, not hidden
    s = PZ.suite(PZ.veto_row_fn(veto_fraction, "STRESSED", 0.3), rows)
    assert s["pc_gate"] is True and s["fire_rate"] == 1.0
    # positioning legs driven directly: discriminates on a spanning grid
    from app.data.positioning import positioning_veto_fraction
    legs = [{"z": -3.0 + i * 0.15, "fii": (i % 3 == 0), "pcr": (i % 4 == 0)} for i in range(40)]
    p = PZ.suite(lambda r: positioning_veto_fraction(r["z"], r["fii"], r["pcr"])[0], legs)
    assert p["pc_gate"] is True and p["nondegenerate"] is True
    c2 = PZ.suite(const, grid)
    assert c2["nondegenerate"] is False  # constant never fires -> degenerate, correctly flagged


def test_friction_matrix_complete():
    m = F.matrix()
    counts = F.modeled_count()
    assert counts["total"] == len(m) == 13
    assert counts["modeled"] >= 5 and counts["unmodeled"] >= 1
    for r in m:
        assert r["cell"] and r["status"] and r["basis"]
        assert r["status"] in ("modeled", "partial", "unmodeled", "unmodeled-bias",
                               "n/a", "n/a-deterministic")
    assert sum(counts[k] for k in ("modeled", "partial", "unmodeled", "na_with_reason")) == len(m)


def test_veto_ablation_cited_not_rerun():
    p = "data/overlay_vs_core_20261007.json"
    assert os.path.exists(p)
    rep = json.load(open(p, encoding="utf-8"))
    assert rep["overlay"]["sharpe"] > rep["core_v3"]["sharpe"]  # 0.776 > 0.705 on record


def test_devil_bypass_unit_and_default():
    from app.agents.graph import _devil_or_default, run_session
    import inspect
    assert "devil_mode" in inspect.signature(run_session).parameters
    assert inspect.signature(run_session).parameters["devil_mode"].default == "on"

    class _T:
        key_evidence = ["bull case"]
    ch = _devil_or_default(_T(), [], "TEST-no-bill", None, "off")
    assert ch.status.value == "HEALTHY" and "ABLATION" in ch.core_claim_restated
    import pytest
    with pytest.raises(ValueError):
        run_session("x", "Y.NS", __import__("datetime").datetime.now(), devil_mode="maybe")
