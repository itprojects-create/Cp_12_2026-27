"""LLM direction arm: capital-allocate the LLM's own evaluated decisions (zero tokens).

Reads stored eval reports (each result already carries the LLM's action/size/fwd
return and cost-adjusted unit PnL), orders sessions chronologically, and compounds
a single book: the LLM "manages" the whole capital, one position at a time. This
answers "how much did the LLM direction engine make on ₹X?" using audited numbers
only — no new LLM calls, no network for the ledger (labels came from the eval).

Counterfactuals on the SAME scenarios and the SAME sizing: force-long and
do-nothing (hold), so the LLM's direction is isolated from sizing.

Usage:
  python scripts/llm_direction_arm.py --report data/eval_report_20261005T091856Z.json --capital 5000000
  python scripts/llm_direction_arm.py --all --capital 5000000   # every stored report, per set
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.data.base import ROUNDTRIP_COST  # noqa: E402


def _trade_pnl(action: str, size: float, fwd: float) -> float:
    sign = {"buy": 1.0, "sell": -1.0, "hold": 0.0}[action]
    traded = 0.0 if action == "hold" else 1.0
    return sign * size * fwd - traded * size * ROUNDTRIP_COST


def build_arm(results: list[dict], capital: float, mode: str) -> dict:
    """Compound one book over time. mode: llm | long | hold."""
    ordered = sorted(results, key=lambda r: (r["as_of"], r["instrument"]))
    c = capital
    curve, trades = [], 0
    for r in ordered:
        if mode == "llm":
            pnl = r.get("pnl", _trade_pnl(r["action"], r["size"], r["fwd_ret"]))
            if r["action"] != "hold":
                trades += 1
        elif mode == "long":
            size = r["size"]
            pnl = _trade_pnl("buy", size, r["fwd_ret"]) if size > 0 else 0.0
            trades += 1 if size > 0 else 0
        else:  # hold — do nothing
            pnl = 0.0
        c *= 1.0 + pnl
        curve.append({"as_of": r["as_of"], "instrument": r["instrument"],
                      "action": r["action"], "size": r["size"],
                      "fwd_ret": r["fwd_ret"], "pnl": round(pnl, 5),
                      "capital_after": round(c, 2)})
    peak, mdd = capital, 0.0
    for k in [capital] + [p["capital_after"] for p in curve]:
        peak = max(peak, k)
        mdd = max(mdd, 1 - k / peak)
    return {"mode": mode, "final": round(c, 2), "profit": round(c - capital, 2),
            "return_pct": round((c / capital - 1) * 100, 2), "max_drawdown_pct": round(mdd * 100, 2),
            "n_traded": trades, "curve": curve}


def run_report(path: str, capital: float) -> dict:
    with open(path, encoding="utf-8") as f:
        rep = json.load(f)
    results = rep.get("results") or []
    arms = {m: build_arm(results, capital, m) for m in ("llm", "long", "hold")}
    dec = [r for r in results if r["label"] in ("long", "short")]
    return {
        "report": path,
        "scenario_set": rep.get("scenario_set", "(unlabeled)"),
        "prompt_note": rep.get("notes", ""),
        "n_scenarios": len(results), "n_decisive": len(dec),
        "accuracy": rep.get("accuracy"), "verdict": rep.get("verdict"),
        "capital": capital,
        "llm_arm": {k: v for k, v in arms["llm"].items() if k != "curve"},
        "always_long_arm": {k: v for k, v in arms["long"].items() if k != "curve"},
        "hold_arm": {k: v for k, v in arms["hold"].items() if k != "curve"},
        "llm_curve": arms["llm"]["curve"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None, help="eval_report_*.json path")
    ap.add_argument("--all", action="store_true", help="process every stored report")
    ap.add_argument("--capital", type=float, default=5000000.0)
    a = ap.parse_args()
    paths = ([a.report] if a.report else
             (sorted(glob.glob(os.path.join("data", "eval_report_*.json"))) if a.all
              else ["data/eval_report_20261005T091856Z.json"]))
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "capital_per_arm": a.capital, "reports": []}
    for p in paths:
        if not os.path.exists(p):
            print("MISSING", p)
            continue
        r = run_report(p, a.capital)
        out["reports"].append(r)
        print(f"{os.path.basename(p):42s} set={r['scenario_set']:20s} "
              f"acc={r['accuracy']} verdict={r['verdict']:12s} "
              f"LLM Rs{r['llm_arm']['profit']:>12,.0f} ({r['llm_arm']['return_pct']:>7.2f}%)  "
              f"long Rs{r['always_long_arm']['profit']:>12,.0f}  hold Rs{r['hold_arm']['profit']:>12,.0f}")
    op = os.path.join("data", "llm_direction_arm.json")
    with open(op, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("report:", op)


if __name__ == "__main__":
    main()
