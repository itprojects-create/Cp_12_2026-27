"""AngelOne SmartAPI read-only adapter (Day 6, NEW_PLAN).

Scope: READ-ONLY. Fetches holdings/positions and maps to PortfolioContext for
the agent's Trader/Risk/PM prompts + paper-logs core signals with the same
0.21% cost model. NEVER places live orders in v1 (no order function exists).

Without creds (env ANGEL_API_KEY/CLIENT_CODE/PIN/TOTP_SECRET absent) every
method raises NotConfigured with a clear message — the agent then runs
flat-unknown, never on fake holdings.
"""
from __future__ import annotations

import os


class NotConfigured(RuntimeError):
    pass


def _require_creds() -> dict:
    creds = {k: os.getenv(k, "") for k in
             ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET")}
    if not all(creds.values()):
        raise NotConfigured(
            "AngelOne creds absent (ANGEL_API_KEY/CLIENT_CODE/PIN/TOTP_SECRET). "
            "Paper trading stays on yfinance; no holdings injected.")
    return creds


def holdings_to_portfolio(raw_positions: list[dict], cash: float | None = None,
                          currency: str = "INR") -> dict:
    """Map broker position rows -> PortfolioContext dict (validated by caller).

    Each row: {symbol (e.g. RELIANCE-EQ), quantity, average_price?}.
    NSE EQ suffix mapped to .NS Yahoo form for prompt consistency.
    """
    positions = []
    for r in raw_positions:
        sym = str(r.get("symbol", "")).upper()
        if sym.endswith("-EQ"):
            sym = sym[:-3] + ".NS"
        try:
            q = float(r.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            continue
        if q == 0:
            continue
        avg = r.get("average_price")
        try:
            avg = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg = None
        positions.append({"ticker": sym, "quantity": q, "average_price": avg})
    return {"cash": cash, "currency": currency, "positions": positions}


def fetch_portfolio() -> dict:
    """Live holdings (read-only). Raises NotConfigured without creds/network."""
    _require_creds()
    try:
        from SmartApi import SmartConnect  # type: ignore
    except ImportError as e:
        raise NotConfigured(f"SmartApi package not installed: {e}") from e
    raise NotConfigured(
        "AngelOne session wiring not completed in v1 — holdings fetch is stubbed. "
        "Wire SmartConnect login + getHolding() here; map via holdings_to_portfolio().")


def paper_log(signals: dict[str, float], out_path: str = "data/paper_signals.jsonl") -> str:
    """Append-only paper log of core targets (no fills invented)."""
    import json
    from datetime import datetime, timezone
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "signals": signals})
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return out_path
