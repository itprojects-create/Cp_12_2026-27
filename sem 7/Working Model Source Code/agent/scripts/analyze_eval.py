"""Honest baseline + significance analysis over every stored eval report (read-only).

For each `data/eval_report_*.json` it scores the agent and trivial constant
rules through the SAME path, adds an exact binomial p-value and a bootstrap CI,
and states whether the agent beats chance and the best constant rule. Uses only
recorded label/action/fwd_ret — no network, no LLM, no tokens.

Usage:  python scripts/analyze_eval.py            # all reports
        python scripts/analyze_eval.py <path.json>
Writes data/baseline_analysis.json.
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.eval.baselines import compare


def _label(path: str, rep: dict) -> str:
    return f"{os.path.basename(path)}  [{rep.get('scenario_set', 'v1-2023-2024')}]"


def main() -> None:
    paths = sys.argv[1:] or sorted(glob.glob("data/eval_report_*.json"))
    if not paths:
        print("no eval reports found")
        return
    out = {}
    for path in paths:
        rep = json.load(open(path, encoding="utf-8"))
        cmp = compare(rep)
        out[os.path.basename(path)] = cmp
        s = cmp["scores"]
        ci = cmp["agent_accuracy_ci95"]
        print(f"\n=== {_label(path, rep)} ===")
        print(f"  agent          acc={s['agent']['accuracy']:.3f} "
              f"({s['agent']['n_correct']}/{s['agent']['n_decisive']}) "
              f"CI95=[{ci[0]:.3f},{ci[1]:.3f}] p={cmp['agent_binomial_p_vs_0_5']:.3f} "
              f"pnl={s['agent']['total_pnl']:+.4f} unit={s['agent']['unit_pnl']:+.4f}")
        for name in ("always_hold", "always_long", "always_short", "agent_inverse"):
            m = s[name]
            print(f"  {name:14s} acc={m['accuracy']:.3f} "
                  f"hold={m['no_edge_hold_rate']:.3f} trade={m['trade_rate']:.3f} "
                  f"pnl={m['total_pnl']:+.4f} unit={m['unit_pnl']:+.4f}")
        print(f"  -> beats_chance={cmp['beats_chance']} | "
              f"best_constant={cmp['best_constant']} ({cmp['best_constant_accuracy']:.3f}) | "
              f"beats_best_constant={cmp['beats_best_constant']}")
    with open("data/baseline_analysis.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote data/baseline_analysis.json")


if __name__ == "__main__":
    main()
