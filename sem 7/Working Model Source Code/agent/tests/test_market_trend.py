"""M4 counter-trend guardrail tests: deterministic, code-level, no LLM.

Index-trend classifier PIT discipline + run_pm must block a LONG into a
confirmed DOWN index and a SHORT into a confirmed UP index, and pass RANGE /
UNKNOWN through untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from app import schemas as S
from app.agents import trader_risk as TR
from app.data.regime import classify_trend


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2023-01-02", periods=len(values), freq="B", tz="UTC")
    return pd.Series(values, index=idx)


def test_classify_trend_up_down_range_unknown():
    up = [100 + i for i in range(120)]
    down = [220 - i for i in range(120)]
    flat = [100.0] * 120
    assert classify_trend(_series(up), 119) == "UP"
    assert classify_trend(_series(down), 119) == "DOWN"
    assert classify_trend(_series(flat), 119) == "RANGE"
    assert classify_trend(_series([100.0] * 30), 29) == "UNKNOWN"   # too short
    assert classify_trend(_series([]), 0) == "UNKNOWN"
    assert classify_trend(_series(up), 999) == "UNKNOWN"           # out of range
    assert classify_trend(_series(up), -1) == "UNKNOWN"


def test_classify_trend_no_lookahead():
    # appending FUTURE bars after asof_idx must not change a past classification
    base = [100 + i for i in range(80)] + [60.0] * 40   # up then collapse
    ext = base + [10.0, 5.0, 300.0]                      # wild future
    assert classify_trend(_series(base), 60) == classify_trend(_series(ext), 60)
    assert classify_trend(_series(ext), 60) == "UP"      # still uptrend at bar 60


def test_market_trend_at_never_raises_offline(monkeypatch):
    import app.data.regime as RG
    class _Boom:
        def ohlcv(self, *a, **k):
            raise RuntimeError("offline")
    monkeypatch.setattr(RG, "YFinanceProvider", _Boom)
    assert RG.market_trend_at(datetime(2024, 6, 10, tzinfo=timezone.utc)) == "UNKNOWN"


# ---- run_pm gate behaviour ----

def _pm_buy(monkeypatch):
    def fake_pm(role, session_id, system, user, schema, fixed=None):
        assert role == "portfolio_manager"
        body = {"action": "buy", "size": 0.08, "rationale": "mock PM approval text",
                "thesis_version": 3}
        body.update(fixed or {})
        return schema(**body)
    monkeypatch.setattr(TR, "call_json", fake_pm)


def _thesis(direction: str) -> S.Thesis:
    return S.Thesis(direction=direction, conviction=0.7, key_evidence=["e1"],
                    key_risks=["r1"], mechanism_type="OTHER")


def _healthy() -> S.Challenge:
    return S.Challenge(status=S.ThesisStatus.HEALTHY,
                       core_claim_restated="Mock thesis causal claim restated here",
                       new_evidence_considered=[], duplicate_risks_discarded=["r1"],
                       direction_symmetry_check_passed=True, reasons=[])


def _proposal(direction: str) -> S.TradeProposal:
    return S.TradeProposal(instrument="T.NS", direction=direction, size_pct=0.08,
                           entry=100.0, stop=95.0, target=110.0)


def _verdicts() -> dict:
    return {k: S.RiskVerdict(approve=True, adjusted_size=0.08, notes="ok")
            for k in ("risk_agg", "risk_con", "risk_neu")}


def test_long_blocked_in_downtrend(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("long"), _healthy(), _proposal("long"),
                    _verdicts(), 3, "mt1", regime="CALM", market_trend="DOWN")
    assert dec.action == "hold" and dec.size == 0.0
    assert "CODE GUARDRAIL" in dec.rationale and "counter-trend long" in dec.rationale


def test_long_allowed_in_uptrend(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("long"), _healthy(), _proposal("long"),
                    _verdicts(), 3, "mt2", regime="CALM", market_trend="UP")
    assert dec.action == "buy" and dec.size == 0.025  # m11 fixed base
    assert "counter-trend" not in dec.rationale


def test_short_blocked_in_uptrend(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("short"), _healthy(), _proposal("short"),
                    _verdicts(), 3, "mt3", regime="CALM", market_trend="UP")
    assert dec.action == "hold" and dec.size == 0.0
    assert "counter-trend short" in dec.rationale


def test_short_allowed_in_downtrend(monkeypatch):
    _pm_buy(monkeypatch)
    dec = TR.run_pm("T.NS", _thesis("short"), _healthy(), _proposal("short"),
                    _verdicts(), 3, "mt4", regime="CALM", market_trend="DOWN")
    assert dec.action == "buy" and dec.size == 0.025  # mock PM action, m11 fixed size


def test_range_and_unknown_never_gate(monkeypatch):
    _pm_buy(monkeypatch)
    for trend in ("RANGE", "UNKNOWN", None):
        dec = TR.run_pm("T.NS", _thesis("long"), _healthy(), _proposal("long"),
                        _verdicts(), 3, f"mt-{trend}", regime="CALM", market_trend=trend)
        assert dec.action == "buy" and dec.size == 0.025  # m11 fixed base
        assert "counter-trend" not in dec.rationale
