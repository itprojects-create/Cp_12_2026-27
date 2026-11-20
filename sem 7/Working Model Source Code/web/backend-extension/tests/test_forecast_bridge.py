import json
from datetime import date, datetime, timedelta, timezone

import pytest

from quantplus_intelligence.forecast import bridge, ledger as L, schema

BULL_EXCESS = 0.03
NEUTRAL_EXCESS = 0.0


def weekdays(day):
    return day.weekday() < 5


def _card(symbol, p, as_of="2026-10-01T10:00:00+00:00", horizon=5, abstain=False):
    return schema.ForecastCard(symbol=symbol, as_of=as_of, horizon=horizon, benchmark="NIFTY50",
                               p_outperform=None if abstain else p,
                               quantiles={"0.1": -0.04, "0.5": 0.0, "0.9": 0.04},
                               vol_forecast=0.03, p_event_shock=0.05,
                               abstain=abstain, abstain_reason="thin" if abstain else "")


def _settle(book, card: schema.ForecastCard, excess: float) -> None:
    recorded = datetime.fromisoformat(card.as_of)
    assert book.record(card, recorded_at=recorded)["duplicate"] is False
    (closes := book.due(date(2026, 10, 9)))
    ids = {d["card_id"]: d for d in closes}
    assert card.card_id in ids, f"card {card.symbol} not due"
    settled = book.settle(card.card_id, excess, settled_at=datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc))
    assert settled["settled"] is True


def test_gate_halts_without_enough_settled_data():
    book = L.Ledger(is_trading_day=weekdays)
    _settle(book, _card("AAA", 0.7), BULL_EXCESS)
    _settle(book, _card("BBB", 0.5), NEUTRAL_EXCESS)
    gate = bridge.edge_gate(book)
    assert gate["horizons"][5]["state"] == "HALT"
    assert gate["horizons"][5]["settled"] == 2
    result = bridge.order_intents(book, gate)
    assert result["intents"] == []


def test_gate_trades_only_when_hurdle_cleared_and_emits_intents():
    book = L.Ledger(is_trading_day=weekdays)
    # 30 settled cards for horizon 5: 12 bullish (p>=0.6) with a positive paid edge, 18 neutral.
    for i in range(12):
        _settle(book, _card(f"B{i:02d}", 0.7), BULL_EXCESS if i < 9 else -0.05)
    for i in range(18):
        _settle(book, _card(f"N{i:02d}", 0.5), NEUTRAL_EXCESS)
    gate = bridge.edge_gate(book)
    h = gate["horizons"][5]
    assert h["state"] == "TRADE", h
    assert h["bull_n"] == 12 and h["settled"] == 30
    assert h["hit_rate"] > 0.5
    assert h["long_edge_after_costs"] == pytest.approx(
        (9 / 12) * BULL_EXCESS + (3 / 12) * -0.05 - bridge.COST_HURDLE)
    order = _card("OPEN", 0.65)
    book.record(order, recorded_at=datetime.fromisoformat(order.as_of))
    intents = bridge.order_intents(book, gate)["intents"]
    assert len(intents) == 1 and intents[0]["symbol"] == "OPEN"
    assert intents[0]["side"] == "BUY" and intents[0]["size_fraction"] > 0
    assert intents[0]["authority"] == "RESEARCH_ONLY"


def test_gate_watches_when_edge_fails_to_mattern_over_costs():
    book = L.Ledger(is_trading_day=weekdays)
    for i in range(12):
        _settle(book, _card(f"B{i:02d}", 0.7), 0.002)  # positive but under the cost hurdle
    for i in range(18):
        _settle(book, _card(f"N{i:02d}", 0.5), NEUTRAL_EXCESS)
    gate = bridge.edge_gate(book)
    assert gate["horizons"][5]["state"] == "WATCH"
    order = _card("OPEN", 0.65)
    book.record(order, recorded_at=datetime.fromisoformat(order.as_of))
    assert bridge.order_intents(book, gate)["intents"] == []


def test_position_fraction_is_half_kelly_capped():
    assert bridge.position_fraction(0.5) == 0.0
    assert bridge.position_fraction(0.3) == 0.0
    assert bridge.position_fraction(0.7) == round(bridge.POSITION_CAP * 0.4 * bridge.HALF_KELLY, 4)
    assert bridge.position_fraction(0.95) <= bridge.POSITION_CAP
