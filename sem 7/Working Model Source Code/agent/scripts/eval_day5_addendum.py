"""Addendum: fire-rate non-degeneracy under Amendment 1 (offline, deterministic).

Does NOT rewrite the published report — it supplements it. Same grids as eval_day5.py.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.overlay import apply_veto, veto_fraction  # noqa: E402
from app.data.positioning import positioning_veto_fraction  # noqa: E402
from app.eval import perturb as PZ  # noqa: E402


def main() -> None:
    rows = [{"ret_5d": -10 + i * 0.8, "dist_hi": -15 + i * 0.6,
             "blackout": (i % 7 == 0)} for i in range(40)]
    mixed = [{"ret_5d": -10 + i * 0.8, "dist_hi": -15 + i * 0.6,
              "regime": ["CALM", "ELEVATED", "STRESSED"][i % 3]} for i in range(40)]
    legs = [{"z": -3.0 + i * 0.15, "fii": (i % 3 == 0), "pcr": (i % 4 == 0)} for i in range(40)]
    suites = {
        "veto_CALM_wide": PZ.suite(PZ.veto_row_fn(veto_fraction, "CALM", 0.7), rows),
        "veto_mixed_regime": PZ.suite(
            lambda r: veto_fraction(r["regime"], 0.35, r["ret_5d"], r["dist_hi"]), mixed),
        "veto_STRESSED_blanket": PZ.suite(
            PZ.veto_row_fn(veto_fraction, "STRESSED", 0.3), rows),
        "positioning_legs": PZ.suite(
            lambda r: positioning_veto_fraction(r["z"], r["fii"], r["pcr"])[0], legs),
        "apply_veto": PZ.suite(
            lambda r: apply_veto({"A": 0.08}, {"A": min(1.0, max(0.0, r["ret_5d"] / 100))})["A"],
            [{"ret_5d": -10 + i * 0.8} for i in range(40)]),
    }
    out = {
        "amendment": "prereg_day5_eval.md Amendment 1 (stepwise tables: PC + non-degeneracy; IDS gate kept for continuous maps)",
        "suites": suites,
        "verdict": {k: {"pc_gate": v["pc_gate"],
                        "stepwise_pass": bool(v["pc_gate"] and v["nondegenerate"]),
                        "continuous_ids_pass": bool(v["ids_gate"])}
                    for k, v in suites.items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join("data", "eval_day5_biting_addendum.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("addendum:", path)


if __name__ == "__main__":
    main()
