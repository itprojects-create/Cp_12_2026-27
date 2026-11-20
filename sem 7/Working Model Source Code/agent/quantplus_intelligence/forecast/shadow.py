"""Pre-registered shadow paper-P&L tracker (forward-only, SHADOW authority).

Registered 2026-11-05, before any post-registration card settled (the file's
first line is the registration record). This addresses the operator's goal
("results must become profitable") without weakening anything: it accumulates a
portfolio view of the strongest bullish cards as forward evidence, never trades
money, never calls a model, and never opens the profitability bridge early.

Fixed rule (documented, not fitted):
- Only cards recorded after the registration timestamp are considered.
- Within the most recent locked batch (max as_of), per horizon (5, 20): top-3
  bullish picks — answerable (not abstaining), p_outperform > 0.5, ranked by
  (|p - 0.5| desc, p desc, symbol asc).
- Hold each pick to its own horizon; net = realised excess - COST_HURDLE
  (0.4% round trip, identical to the bridge).
- Scoring reads ONLY the main ledger's forward settlements; no price fetching,
  no backfill, and interim data never influences a pick or a score.

The profitability bridge remains authoritative — SHADOW picks are forward-
testing evidence for the trade gate, not a bypass.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

COST_HURDLE = 0.004     # same round-trip floor the bridge uses
TOP_K = 3               # bullish picks per horizon per batch
MIN_P = 0.5             # strictly bullish
AUTHORITY = "SHADOW — paper P&L evidence only; not the profitability gate"

RULE = (
    "Evening batch, latest as_of only, per horizon: top-3 bullish cards "
    f"(answerable, p > {MIN_P}; tie-break |p-0.5| desc, p desc, symbol asc), "
    f"held to the card horizon; net = realised excess - {COST_HURDLE:.1%} round trip. "
    "Fixed before these cards settled; forward-only; interim data not used."
)

_REPORTS = Path(os.environ.get("FORECAST_REPORT_DIR", "data/forecast_reports"))
DEFAULT_PATH = _REPORTS / "paper_pnl.jsonl"
_LOCK = threading.Lock()


def _path(path: Path | None) -> Path:
    return path or DEFAULT_PATH


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn line from a killed process; the next run re-appends
    return out


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def ensure_registration(path: Path | None = None, now: datetime | None = None) -> dict:
    """Idempotently keep the fixed registration as the file's first line."""
    path = _path(path)
    with _LOCK:
        existing = _lines(path)
        for line in existing:
            if line.get("type") == "registration":
                return line
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        head = {"type": "registration", "registered_utc": stamp, "rule": RULE,
                "scored_from": "main ledger forward settlements only", "authority": AUTHORITY,
                "note": "post-registration picks only; pre-registration batches excluded"}
        _append(path, head)
        return head


def _registered_at(path: Path) -> datetime | None:
    for line in _lines(path):
        if line.get("type") == "registration":
            try:
                return datetime.fromisoformat(line["registered_utc"])
            except (KeyError, ValueError):
                return None
    return None


def _card_id_from_payload(card: dict):
    from . import schema
    return schema.card_from_dict(card).card_id


def _eligible(rows: list[dict], registered: datetime | None) -> list[dict]:
    out = []
    for row in rows:
        card = dict(row["card"])
        try:
            card["_card_id"] = _card_id_from_payload(row["card"])
        except (KeyError, ValueError, TypeError):
            continue
        if card.get("abstain"):
            continue
        p = card.get("p_outperform")
        if p is None or p <= MIN_P:
            continue
        try:
            stamped = datetime.fromisoformat(row["recorded_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if registered is None or stamped < registered:
            continue
        card["_recorded_at"] = row["recorded_at"]
        out.append(card)
    return out


def pick(book, path: Path | None = None, now: datetime | None = None) -> dict:
    """Record the shadow picks for the most recent post-registration batch."""
    path = _path(path)
    ensure_registration(path, now)
    registered = _registered_at(path)
    now = now or datetime.now(timezone.utc)
    eligible = _eligible(book.cards(limit=100000), registered)
    if not eligible:
        return {"job": "paper.pick", "picked": 0, "batch_as_of": None,
                "picks": [], "note": "no post-registration batch yet",
                "registration": RULE, "authority": AUTHORITY}
    batch_as_of = max(card["as_of"] for card in eligible)
    existing = {line["card_id"] for line in _lines(path) if line.get("type") == "pick"}
    added, picks = 0, []
    for horizon in (5, 20):
        group = [card for card in eligible
                 if card["as_of"] == batch_as_of and card["horizon"] == horizon]
        group.sort(key=lambda c: (-abs(float(c["p_outperform"]) - 0.5),
                                  -float(c["p_outperform"]), c["symbol"]))
        for card in group[:TOP_K]:
            cid = card["_card_id"]
            if cid in existing:
                continue
            line = {"type": "pick", "card_id": cid, "symbol": card["symbol"],
                    "horizon": horizon, "as_of": card["as_of"], "p": card["p_outperform"],
                    "picked_at": now.isoformat(), "notional": 100,
                    "rule": RULE, "authority": AUTHORITY}
            with _LOCK:
                _append(path, line)
            existing.add(cid)
            added += 1
            picks.append({"symbol": card["symbol"], "horizon": horizon, "p": card["p_outperform"]})
    return {"job": "paper.pick", "batch_as_of": batch_as_of, "picked": added, "picks": picks,
            "note": "" if added else "latest batch already picked",
            "registration": RULE, "authority": AUTHORITY}


def settle_picks(book, path: Path | None = None, now: datetime | None = None) -> dict:
    """Score recorded picks once, from the main ledger's forward settlements only."""
    path = _path(path)
    now = now or datetime.now(timezone.utc)
    settled_cards = {}
    for row in book.cards(settled=True, limit=100000):
        try:
            settled_cards[_card_id_from_payload(row["card"])] = (
                row["outcome"] or {}, row["settled_at"])
        except (KeyError, ValueError, TypeError):
            continue
    done = {line["card_id"] for line in _lines(path) if line.get("type") == "settle"}
    scored = []
    with _LOCK:
        for line in _lines(path):
            if line.get("type") != "pick":
                continue
            cid = line["card_id"]
            if cid in done or cid not in settled_cards:
                continue
            outcome, settled_at = settled_cards[cid]
            excess = outcome.get("excess_return")
            if excess is None:
                continue
            net = float(excess) - COST_HURDLE
            _append(path, {"type": "settle", "card_id": cid, "symbol": line["symbol"],
                           "horizon": line["horizon"], "as_of": line["as_of"],
                           "excess_return": float(excess), "net": net,
                           "outperformed": int(float(excess) > 0),
                           "settled_at": (settled_at or now.isoformat()),
                           "scored_at": now.isoformat(), "authority": AUTHORITY})
            done.add(cid)
            scored.append({"symbol": line["symbol"], "horizon": line["horizon"], "net": net})
    return {"job": "paper.settle", "scored": len(scored), "results": scored, "authority": AUTHORITY}


def summary(path: Path | None = None) -> dict:
    path = _path(path)
    lines = _lines(path)
    picks = {line["card_id"]: line for line in lines if line.get("type") == "pick"}
    settled = {line["card_id"]: line for line in lines if line.get("type") == "settle"}
    nets = [line["net"] for line in settled.values()]
    by_horizon = {}
    for horizon in (5, 20):
        vals = [line["net"] for line in settled.values() if line.get("horizon") == horizon]
        open_n = sum(1 for line in picks.values()
                     if line.get("horizon") == horizon and line["card_id"] not in settled)
        if vals or open_n:
            by_horizon[horizon] = {"picks": len(vals) + open_n, "settled": len(vals),
                                   "open": open_n, "hits": sum(v > 0 for v in vals),
                                   "mean_net": mean(vals) if vals else None,
                                   "sum_net": sum(vals) if vals else None}
    return {"picks": len(picks), "settled": len(settled), "open": len(picks) - len(settled),
            "hits": sum(v > 0 for v in nets), "mean_net": mean(nets) if nets else None,
            "sum_net": sum(nets) if nets else None, "by_horizon": by_horizon,
            "cost_hurdle": COST_HURDLE, "authority": AUTHORITY,
            "disclaimer": "SHADOW paper evidence; horizons may still be open; this is not money P&L.",
            # W0.4 correction labels (additive): `net` here is benchmark-relative excess
            # minus a flat 0.4% hurdle — research evidence, not investor cash P&L.
            "metric_semantics": {
                "net": "v2 benchmark-relative excess minus a flat 0.4% hurdle; NOT cash P&L",
                "corrected_metrics": "quantplus_intelligence.research_v3.economics "
                                     "(v3_trade_cash_pnl: integer-paise itemised charges)",
                "stream": "V2 pre-registered paper_pnl.jsonl; the V3.1 stream is a separate "
                          "file and must not overwrite this one",
            }}


def run(book, path: Path | None = None) -> dict:
    """Evening paper job: record picks for the latest batch, then score maturations."""
    ensure_registration(path)
    pick_out = pick(book, path)
    settle_out = settle_picks(book, path)
    return {"job": "paper", "batch_as_of": pick_out["batch_as_of"],
            "picked": pick_out["picked"], "picks": pick_out["picks"],
            "picked_note": pick_out["note"], "scored": settle_out["scored"],
            "summary": summary(path),
            "claim": "SHADOW — forward-testing stream for the trade gate; "
                     "bridge.edge_gate remains the only path to order intents."}
