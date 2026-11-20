import json
from datetime import datetime, timezone
from app import schemas as S
from app.agents import _util


def test_invalid_claims_are_retried_and_never_returned(monkeypatch):
    calls = []
    def invalid(**kwargs):
        calls.append(kwargs)
        return json.dumps({"summary": "The price=500", "signals": [{"name": "price", "value": 500, "direction": "neutral"}], "confidence": .2, "evidence": []})
    monkeypatch.setattr(_util.gateway, "complete_json", invalid)
    result = _util.call_json("technical", "grounding-test", "system", "price=100 volume=500", S.AnalystReport, {"agent": "technical"}, grounding="price=100 volume=500", as_of=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert result.summary == "Insufficient verifiable evidence; abstaining."
    assert result.signals == [] and result.evidence == [] and result.confidence == 0
    assert len(calls) == 2
    assert "Unsupported research claims" in calls[1]["user"]


def test_malformed_schema_twice_abstains_instead_of_failing_the_session(monkeypatch):
    """2026-10-27 14:05 IST: the macro agent returned JSON missing `summary` twice.

    With no abstention path for plain schema failures, the session aborted AFTER
    the other analysts had already billed their calls — wasted quota, no result.
    A code-owned abstention must replace a malformed analyst payload instead.
    """
    calls = []
    def malformed(**kwargs):
        calls.append(kwargs)
        return json.dumps({"signals": []})  # missing summary/confidence/evidence
    monkeypatch.setattr(_util.gateway, "complete_json", malformed)
    result = _util.call_json("macro", "schema-fail", "system", "nifty ret20d=+1.2%",
                             S.AnalystReport, {"agent": "macro"},
                             grounding="nifty ret20d=+1.2%",
                             as_of=datetime(2026, 10, 27, tzinfo=timezone.utc))
    assert result.summary == "Insufficient verifiable evidence; abstaining."
    assert result.signals == [] and result.evidence == [] and result.confidence == 0
    assert result.agent == "macro"
    assert len(calls) == 2
    assert "FAILED validation" in calls[1]["user"]
