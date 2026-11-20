"""P2 taxonomy/abstention/blackout tests (§78 classification + blackout). Hermetic."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.events import blackout as BO
from app.events import classify as CL
from app.events import taxonomy as TAX
from app.events.schemas import Announcement


def _ann(symbol="INFY.NS", day=9, etype="BOARD_MEETING", bc=True, sev=0.6):
    return Announcement(source="NSE", symbol=symbol, event_type=etype, severity=sev,
                        source_timestamp=f"2026-10-{day:02d}T10:00:00+00:00",
                        effective_timestamp=f"2026-10-{day:02d}T10:00:00+00:00",
                        blackout_candidate=bc)


ASOF = datetime(2026, 10, 10, tzinfo=timezone.utc)


def test_taxonomy_versioned_and_mapped():
    assert TAX.VERSION == "EVENT_TAXONOMY_V1" and len(TAX.TAXONOMY_V1) >= 20
    assert TAX.from_legacy("SPLIT_BONUS") == "CORPORATE_ACTION"
    assert TAX.from_legacy("MERGER") == "M_AND_A"
    assert TAX.from_legacy("NOPE") == "UNKNOWN"
    assert TAX.is_valid("EARNINGS") is True
    with pytest.raises(ValueError):
        TAX.is_valid("EARNINGS", "TAXONOMY_V99")


def test_triage_abstains_never_forces():
    assert CL.triage("")["decision"] == "ABSTAIN"
    assert CL.triage("Results ok")["decision"] == "ABSTAIN"  # too short
    assert CL.triage("Routine disclosure about office timings")["decision"] == "ABSTAIN"
    hit = CL.triage("Board Meeting to consider dividend")
    assert hit["decision"] == "CLASSIFY" and hit["rule"] is not None


def test_blackout_family_frozen_shape():
    assert BO.BLACKOUT_FAMILY_VERSION == "BLACKOUT_FAMILY_V1"
    ids = [r.rule_id for r in BO.BLACKOUT_FAMILY_V1]
    assert ids == ["B0", "B1", "B2", "B3"]
    import json
    frozen = json.load(open("data/blackout_family_v1.json", encoding="utf-8"))
    assert frozen["family_version"] == "BLACKOUT_FAMILY_V1"
    assert [r["rule_id"] for r in frozen["rules"]] == ids
    live = [r.frozen_dict() for r in BO.BLACKOUT_FAMILY_V1]
    assert live == frozen["rules"]  # code matches frozen artifact


def test_rule_activation_and_taxonomy_gate():
    b1, b2, b3 = BO.BLACKOUT_FAMILY_V1[1:]
    assert BO.rule_active(BO.BLACKOUT_FAMILY_V1[0], "INFY.NS", ASOF,
                          [_ann()])[0] is False  # B0 control never fires
    assert BO.rule_active(b1, "INFY.NS", ASOF, [_ann(day=9)])[0] is False  # pre-window
    assert BO.rule_active(b1, "INFY.NS", ASOF, [_ann(day=10)])[0] is True  # event day
    assert BO.rule_active(b2, "INFY.NS", ASOF, [_ann(day=9)])[0] is True  # +next covers
    assert BO.rule_active(b3, "INFY.NS", ASOF, [_ann(day=11)])[0] is True  # pre covers
    div = _ann(day=10, etype="DIVIDEND")  # not in eligible set
    assert BO.rule_active(b1, "INFY.NS", ASOF, [div])[0] is False
    assert BO.rule_active(b1, "INFY.NS", ASOF, [])[1].startswith("unavailable")


def test_blackout_shrink_only_boundaries():
    A = BO.apply_to_position
    assert A(0.0, 0.05, True) == 0.0  # cannot create
    assert A(0.05, 0.09, True) == 0.05  # cannot increase
    assert A(0.05, 0.02, True) == 0.02  # decreases pass (exits never blocked)
    assert A(0.05, 0.0, True) == 0.0  # full exit passes
    assert A(0.05, 0.09, False) == 0.09  # inactive: control unchanged
    assert A(0.0, 0.0, True) == 0.0


def test_rule_to_dsl_bridge():
    from app.foundry import dsl as DSL
    empty = BO.rule_to_dsl(BO.BLACKOUT_FAMILY_V1[0])
    assert empty == {"ops": []}
    prog = BO.rule_to_dsl(BO.BLACKOUT_FAMILY_V1[3])
    s = DSL.compile_program(prog)
    assert s.evaluate_row({"blackout": True})["pass"] is False
    assert s.evaluate_row({"blackout": False})["pass"] is True
