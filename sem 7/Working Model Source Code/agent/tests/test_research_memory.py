"""Research memory tests (migration Phase 3). Hermetic via conftest temp DB."""
from __future__ import annotations

import pytest

from app.db import sqlite_conn
from app.research_memory import corpses as CORP
from app.research_memory import evidence as EV
from app.research_memory import lineage as LIN
from app.research_memory import retrieval as RET
from app.research_memory import store as ST


@pytest.fixture(autouse=True)
def _clean():
    ST.init_tables()
    yield
    db = sqlite_conn()
    db.execute("DELETE FROM research_hypotheses WHERE fp LIKE 'hyp-%' AND body LIKE '%TEST-MEM%'")
    db.execute("DELETE FROM research_hypotheses WHERE hypothesis_id LIKE 'TEST-%'")
    db.execute("DELETE FROM research_experiments WHERE hypothesis_fp NOT IN "
               "(SELECT fp FROM research_hypotheses)")
    db.execute("DELETE FROM research_corpses WHERE body LIKE '%TEST-MEM%'")
    db.execute("DELETE FROM research_lineage WHERE child_fp LIKE 'TEST-%'")
    db.commit()


def _hyp(hid="TEST-MEM-H1", thesis="Delivery exhaustion veto interaction test memory",
         title="TEST-MEM exhaust veto title here"):
    return {"hypothesis_id": hid, "title": title,
            "thesis": thesis + " with enough words to pass validation length floors.",
            "economic_reason": "TEST-MEM economic rationale with enough words here.",
            "strategy_family": "veto_filter", "required_features": ["delivery_z"],
            "claimed_mechanism": "TEST-MEM fade mechanism",
            "falsification_tests": ["placebo"], "novelty_claim": "TEST-MEM novelty claim here.",
            "estimated_research_cost": 100.0}


def test_submit_and_exact_duplicate():
    r1 = ST.submit_hypothesis(_hyp())
    assert r1["stored"] is True and r1["status"] == "PROPOSED"
    r2 = ST.submit_hypothesis(_hyp())
    assert r2["stored"] is False and r2["status"] == "DUPLICATE"


def test_corpse_blocks_rediscovery_until_new_evidence():
    ST.submit_hypothesis(_hyp(hid="TEST-MEM-H2"))
    hypo_fp = [h for h in ST.list_hypotheses()
               if h["hypothesis_id"] == "TEST-MEM-H2"][0]["fp"]
    exp = ST.record_experiment(hypo_fp, {"note": "TEST-MEM"})
    out = ST.record_outcome(exp, "FAILED_BACKTEST", {"sharpe": -0.2},
                            failure_reason="TEST-MEM no edge net of costs")
    assert out["corpse"]["fp"] == hypo_fp
    corpse = ST.get_corpse_by_fp(hypo_fp)
    assert corpse is not None and "TEST-MEM" in corpse["failure_reason"]
    assert "unseen regime" in corpse["evidence_required"]
    # resubmission of the failed idea confronts the corpse (not DUPLICATE)
    again = ST.submit_hypothesis(_hyp(hid="TEST-MEM-H2B"))
    assert again["stored"] is False and again["status"] == "DEAD_MATCH"
    assert "evidence_required" in (again["corpse"] or {})
    # ...unless genuinely new evidence is supplied
    reopened = ST.submit_hypothesis(_hyp(hid="TEST-MEM-H2C"),
                                    new_evidence="TEST-MEM new PIT regime data")
    assert reopened["stored"] is True


def test_retrieval_surfaces_corpse_with_format():
    hypo = _hyp(hid="TEST-MEM-H3", thesis="Delivery percentage predicts direction test")
    ST.submit_hypothesis(hypo)
    h = [x for x in ST.list_hypotheses() if x["hypothesis_id"] == "TEST-MEM-H3"][0]
    CORP.bury(h["fp"], {"title": "TEST-MEM delivery direction",
                        "thesis": "Delivery percentage predicts direction test",
                        "allowed_reuse": "exhaustion / risk context only"},
              "TEST-MEM failed 4 ways", {})
    hits = RET.retrieve("delivery predicts direction exhaustion", top_k=3)
    assert any(x["kind"] == "corpse" for x in hits)
    corpse = [x for x in hits if x["kind"] == "corpse"][0]
    block = RET.format_corpse_match({"title": "delivery direction idea"}, corpse)
    assert "MATCHED PRIOR CORPSE" in block and "exhaustion / risk context only" in block
    assert "unseen regime" in block


def test_lineage_tree():
    LIN.link("TEST-C1", "TEST-P0", "mutated-from")
    LIN.link("TEST-C2", "TEST-C1", "mutated-from")
    t = LIN.tree("TEST-P0")
    assert t["fp"] == "TEST-P0" and t["children"][0]["fp"] == "TEST-C1"
    assert t["children"][0]["children"][0]["fp"] == "TEST-C2"
    assert LIN.tree("TEST-LEAF") == {"fp": "TEST-LEAF", "children": []}


def test_evidence_record_requires_fields():
    with pytest.raises(ValueError):
        EV.build_evidence_record(hypothesis_id="H")
    rec = EV.build_evidence_record(
        hypothesis_id="H", hypothesis_fp="hyp-x", creator_agent="factor",
        strategy_fp="strat-x", parameter_fp="par-x", data_fp="data-x",
        data_status="forward-only", universe=["A.NS"], features=["f"],
        code_version="abc123", gateset="GATESET_FROZEN_20260918",
        benchmark="NIFTY50_TRI", cost_model="env-v1")
    assert rec["status"] == "EXPERIMENTING"
    m = EV.manifest("EXP-00001", rec)
    assert m["experiment_id"] == "EXP-00001" and m["gate_version"].startswith("GATESET")
