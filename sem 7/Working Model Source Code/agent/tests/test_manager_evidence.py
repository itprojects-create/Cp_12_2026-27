"""Manager/debate evidence grounding (data/prereg_manager_evidence.md).

Deterministic, no LLM: pins that the deciders actually RECEIVE the analyst
signals they are instructed to tally, and that the tally is code-computed.
Before the fix the ledger was `summary` prose only and `.signals` was write-only.
"""
from __future__ import annotations

from app import schemas as S
from app.agents._util import evidence_ledger
from app.agents import manager as MGR
from app.agents import debate as DB


def _report(agent, conf, signals):
    return S.AnalystReport(
        agent=agent, summary=f"{agent} summary text here",
        signals=[S.Signal(name=n, value=v, direction=d) for n, v, d in signals],
        confidence=conf, evidence=[])


def _reports():
    return [
        _report("technical", 0.6, [("trend", 2.5, "bullish"), ("mom", 7.8, "bullish"),
                                   ("vol", 0.7, "neutral")]),
        _report("events", 0.4, [("surprise", -37.5, "bearish")]),
    ]


def test_ledger_includes_every_signal_and_deterministic_tally():
    led = evidence_ledger(_reports())
    # signals are actually present (previously dropped before the decider)
    assert "trend=2.5 bullish" in led
    assert "surprise=-37.5 bearish" in led
    # tally is exact and code-owned
    assert "bullish=2 bearish=1 neutral=1" in led
    assert "signal_margin=+1" in led
    assert "mean_conf=0.50" in led


def test_manager_receives_evidence_ledger(monkeypatch):
    captured = {}

    def fake_call(role, session_id, system, user, schema, fixed=None):
        captured["system"] = system
        captured["user"] = user
        return S.Thesis(direction="flat", conviction=0.4, key_evidence=["e"],
                        key_risks=["r"], mechanism_type="OTHER")

    monkeypatch.setattr(MGR, "call_json", fake_call)
    MGR.run_manager(_reports(), [], "sid")

    assert "TALLY" in captured["user"]
    assert "trend=2.5 bullish" in captured["user"]
    # prompt must direct the model to the provided tally, not to recount blind
    assert "never recount or guess" in captured["system"].lower()


def test_debate_digest_includes_signals_and_tally():
    d = DB._digest(_reports())
    assert "TALLY" in d
    assert "surprise=-37.5 bearish" in d
