"""Broker-neutral portfolio context (Day 2 T2.1, NEW_PLAN).

Three states stay distinct: position vs flat book vs None (not provided).
Treating "not provided" as "flat" would invent a fact about the caller's account.
Borrowed shape from TradingAgents portfolio.py, re-implemented PIT-clean.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field


class Position(BaseModel):
    model_config = {"frozen": True}
    ticker: str = Field(description="Instrument symbol, e.g. RELIANCE.NS")
    quantity: float = Field(description="Signed units held; negative is short")
    average_price: float | None = Field(default=None, description="Average entry price per unit")


class PortfolioContext(BaseModel):
    model_config = {"frozen": True}
    cash: float | None = Field(default=None)
    currency: str | None = Field(default=None)
    positions: list[Position] = Field(default_factory=list)

    def position_in(self, ticker: str) -> Position | None:
        return next((p for p in self.positions if p.ticker.upper() == ticker.strip().upper()), None)

    def render(self, ticker: str) -> str:
        symbol = ticker.strip().upper()
        held = self.position_in(symbol)
        if held is None:
            lines = [f"- No current position in {symbol}"]
        else:
            price = f", average price {held.average_price:,.2f}" if held.average_price is not None else ""
            lines = [f"- Current position in {symbol}: {held.quantity:,.4g} units{price}"]
        if self.cash is not None:
            lines.append(f"- Cash available: {self.cash:,.2f}{' ' + self.currency if self.currency else ''}")
        others = [p for p in self.positions if p is not held]
        if others:
            lines.append("- Other positions: " + ", ".join(f"{p.ticker.upper()} {p.quantity:,.4g}" for p in others))
        return "Portfolio at the analysis date:\n" + "\n".join(lines)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def load_portfolio(path: str | Path) -> PortfolioContext:
    from pydantic import ValidationError
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return PortfolioContext.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"portfolio file {path} is not usable: {exc}") from exc
