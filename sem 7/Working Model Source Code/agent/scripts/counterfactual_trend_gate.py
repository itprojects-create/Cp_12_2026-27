"""Offline counterfactual: what would the M4 counter-trend guardrail have done?

Replays every recorded eval report's decisions through the new gate using PIT
index-trend from the cached ^NSEI files — NO LLM calls, NO tokens. It answers
"would the gate have helped on the sets we already ran?", which is IN-SAMPLE
evidence (the rule was motivated by these results) and therefore directional
only; a live eval on a fresh set is still required before trusting it.

Rule (mirrors app/agents/trader_risk.run_pm): a BUY with index trend DOWN, or a
SELL with index trend UP, becomes HOLD/size-0. Everything else is unchanged.

Usage:  python scripts/counterfactual_trend_gate.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.regime import classify_trend
from app.eval.baselines import DIRECTION, SIGN, load_rows
from app.data.base import ROUNDTRIP_COST

CACHE_DIR = "data/yf_cache"


def _trend_for(as_of: str) -> str:
    """PIT index trend from the cached ^NSEI slice for this as_of date."""
    key = f"{CACHE_DIR}/^NSEI_1d_{as_of}_v2.csv"
    if not os.path.exists(key):
        return "UNKNOWN"
    df = pd.read_csv(key, index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    cutoff = datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc)
    closes = df[df.index <= cutoff]["Close"].dropna()
    if len(closes) < 2:
        return "UNKNOWN"
    return classify_trend(closes, len(closes) - 1)


def _pnl(rows, gated: dict) -> float:
    total = 0.0
    for r in rows:
        act = gated[(r["instrument"], r["as_of"])]
        cost = ROUNDTRIP_COST if act != "hold" else 0.0
        total += SIGN[act] * r["size"] * r["fwd_ret"] - r["size"] * cost
    return total


def _metrics(rows, gated: dict) -> dict:
    dec = [r for r in rows if r["label"] in ("long", "short")]
    flat = [r for r in rows if r["label"] == "flat"]
    correct = sum(1 for r in dec if DIRECTION[gated[(r["instrument"], r["as_of"])]] == r["label"])
    traded = sum(1 for r in rows if gated[(r["instrument"], r["as_of"])] != "hold")
    return {
        "accuracy": correct / len(dec) if dec else 0.0,
        "n_decisive": len(dec), "n_correct": correct,
        "no_edge_hold_rate": sum(1 for r in flat if gated[(r["instrument"], r["as_of"])] == "hold") / len(flat) if flat else 1.0,
        "trade_rate": traded / len(rows) if rows else 0.0,
        "total_pnl": _pnl(rows, gated),
    }


def main() -> None:
    paths = sorted(glob.glob("data/eval_report_*.json"))
    print(f"{'report':44s} {'acc':>6s} {'->gated':>8s} {'pnl':>9s} {'->gated':>9s} {'trend mix'}")
    tot_before = tot_after = 0.0
    for path in paths:
        rep = json.load(open(path, encoding="utf-8"))
        rows = load_rows(rep)
        before = {(r["instrument"], r["as_of"]): r["action"] for r in rows}
        gated = dict(before)
        mixes: dict[str, int] = {}
        for r in rows:
            tr = _trend_for(r["as_of"])
            mixes[tr] = mixes.get(tr, 0) + 1
            if (r["action"] == "buy" and tr == "DOWN") or (r["action"] == "sell" and tr == "UP"):
                gated[(r["instrument"], r["as_of"])] = "hold"
        mb, ma = _metrics(rows, before), _metrics(rows, gated)
        tot_before += mb["total_pnl"]
        tot_after += ma["total_pnl"]
        changed = sum(1 for k in before if before[k] != gated[k])
        print(f"{os.path.basename(path):44s} {mb['accuracy']:6.3f} {ma['accuracy']:8.3f} "
              f"{mb['total_pnl']:+9.4f} {ma['total_pnl']:+9.4f} "
              f"{mixes} (blocked {changed})")
    print(f"\nPOOLED unit-book PnL: before={tot_before:+.4f}  after={tot_after:+.4f}  "
          f"delta={tot_after - tot_before:+.4f}")
    print("IN-SAMPLE (rule motivated by these sets) — live fresh-set eval still required.")


if __name__ == "__main__":
    main()
