"""Profitability bridge: only the scoreboard may turn a forecast into a trade intent.

The bridge is a deterministic translator between two lanes the project already has:

  scoreboard (settled, forward-only scores) -> edge gate -> trade intents

It owns no money, calls no model, and never changes a balance. Intents are
RESEARCH_ONLY artifacts for the paper book; a gate that lacks settled data HALTS
every intent. Longs only: NSE cash-equity delivery cannot short.

Hurdles (documented, not fitted):
- cost_hurdle: one delivery round trip (STT + charges + slippage) ~0.25-0.35%;
  0.004 (0.4%) is the conservative default. An edge must clear it.
- min_n: statistical honesty floor per horizon before any trade claim.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

MIN_SETTLED = 30        # per horizon; below this the gate resumes state HALT
MIN_BULL = 10           # minimum bullish-slice cards before a long claim; else WATCH
TRADE_P = 0.6           # a card trades only above this probability
COST_HURDLE = 0.004     # fraction; delivery round-trip cost floor
POSITION_CAP = 0.10     # max fraction of paper equity in one card idea
HALF_KELLY = 0.5        # size multiplier; full Kelly is never used
REPORTS = Path(os.environ.get("FORECAST_REPORT_DIR", "data/forecast_reports")) / "bridge"


def _settled(book) -> list[dict]:
    return [r for r in book.cards(settled=True, limit=100000) if not r["card"]["abstain"]]


def edge_gate(book, min_settled: int = MIN_SETTLED, trade_p: float = TRADE_P,
              cost_hurdle: float = COST_HURDLE) -> dict:
    """Per-horizon verdict from forward-settled cards only.

    - long edge = mean realised excess of cards with p >= trade_p minus the cost hurdle
    - state: HALT (too few settled) < WATCH (data exists, hurdle not cleared)
             < TRADE (hurdle cleared with a positive hit rate above 0.5)
    A prior false TRADE is not re-opened by new data here; scoring stays honest
    because every claim re-derives from settled rows on every run.
    """
    settled = _settled(book)
    by_horizon: dict[int, list[dict]] = {}
    for r in settled:
        by_horizon.setdefault(r["card"]["horizon"], []).append(r)

    gates = {}
    for horizon, rows in sorted(by_horizon.items()):
        bull = [r for r in rows if (r["card"].get("p_outperform") or 0) >= trade_p]
        long_edge = None
        hit = None
        if bull:
            hit = mean(r["outcome"]["outperformed"] for r in bull)
            long_edge = mean(r["outcome"]["excess_return"] for r in bull) - cost_hurdle
        if len(rows) < min_settled:
            state = "HALT"
        elif bull and len(bull) >= MIN_BULL and long_edge is not None and long_edge > 0 and hit > 0.5:
            state = "TRADE"
        else:
            state = "WATCH"
        gates[horizon] = {
            "state": state, "settled": len(rows), "bull_n": len(bull),
            "hit_rate": hit, "long_edge_after_costs": long_edge,
            "need_for_halt_end": max(0, min_settled - len(rows)),
            "trade_p": trade_p, "cost_hurdle": cost_hurdle,
        }
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "horizons": gates,
            "claim": "every number re-derives from settled ledger rows; no state persists",
            # W0.4 correction labels (additive): the metric above is benchmark-relative
            # research evidence, never investor cash P&L. Corrected versioned metrics
            # (v3_benchmark_relative / v3_net_absolute / v3_trade_cash_pnl) live in
            # quantplus_intelligence.research_v3.economics with itemised paise costs.
            "metric_semantics": {
                "excess_return": "v2 benchmark-relative excess vs NIFTY; NOT cash profit",
                "long_edge_after_costs": "benchmark-relative spread minus a flat "
                                         f"{cost_hurdle:.1%} hurdle; the hurdle is notional-size "
                                         "independent and not an executable cost model",
                "corrected_metrics": "quantplus_intelligence.research_v3.economics "
                                     "(v3_trade_cash_pnl: integer-paise itemised charges)",
                "authority": "TRADE state authorises research intents only; RESEARCH_ONLY "
                             "artifacts feed the paper book, never live orders",
            }}


def position_fraction(p: float, size_cap: float = POSITION_CAP) -> float:
    """Half-Kelly-flavoured size for one card: cap * 2*(p-0.5), halved, floored at 0.

    Crude until meta-labeling has 50 settled core labels; deliberately
    conservative (half of a capped two-times-edge heuristic).
    """
    if p <= 0.5:
        return 0.0
    raw = size_cap * min(1.0, 2.0 * (p - 0.5)) * HALF_KELLY
    return round(min(raw, size_cap), 4)


def order_intents(book, gate: dict, trade_p: float = TRADE_P) -> dict:
    """Unresolved cards above the threshold become intents only if the gate says TRADE."""
    unresolved = [r for r in book.cards(settled=False, limit=100000) if not r["card"]["abstain"]]
    intents, skipped = [], 0
    for r in unresolved:
        card = r["card"]
        horizon_gate = gate["horizons"].get(card["horizon"], {})
        p = card.get("p_outperform")
        if p is None or p < trade_p:
            skipped += 1
            continue
        if horizon_gate.get("state") != "TRADE":
            skipped += 1
            continue
        intents.append({
            "card_id": card.get("card_id"), "symbol": r["symbol"] if "symbol" in r else card.get("symbol"),
            "horizon": card["horizon"], "side": "BUY",
            "p": p, "as_of": card.get("as_of"),
            "size_fraction": position_fraction(p),
            "authority": "RESEARCH_ONLY",
            "falsifiers": card.get("falsifiers", []),
            "note": "consume into the paper book; reduce-or-hold on a tripwire WEAKENED",
        })
    return {"gate": gate, "intents": intents, "skipped": skipped,
            "authority": "intents are research artifacts; nothing here mutates an account"}


def run(book, trade_p: float = TRADE_P) -> dict:
    """Settle-aware bridge job: gate + intents + a dated artifact on disk."""
    gate = edge_gate(book, trade_p=trade_p)
    result = order_intents(book, gate, trade_p=trade_p)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    path = REPORTS / f"bridge-{stamp.date().isoformat()}.json"
    snapshot = {
        "generated_at": stamp.isoformat(),
        "gate": gate,
        "intents": result["intents"],
        "skipped": result["skipped"],
    }
    path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    return {"job": "bridge", "gate": gate, "intents": len(result["intents"]),
            "skipped": result["skipped"], "written": str(path)}
