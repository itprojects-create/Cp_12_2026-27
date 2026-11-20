"""Overlay ablation A/B/C: empirical verdict, zero new inference spend (§23).

Arms (frozen operator, no parameters tuned — this measures, not optimizes):
  A = deterministic core (fixed 0.05 long every scenario — the no-overlay control)
  B = core + deterministic veto table (synthetic operator check: vetoes constructed
      blowoffs, passes normal flow — proves the deterministic overlay behaves)
  C = core + LLM overlay via llm_overlay_size (veto/resize only), driven by CACHED
      eval-session LLM views (action/size) against their recorded forward returns.
      Zero new LLM calls; reports whose labels predate the split-adjust fix are
      included with a comparability disclosure (as-is, per repo discipline).

Book convention (matches scripts/llm_direction_arm.py): ₹50L sequential book,
compounded per scenario in (as_of, instrument) order; pnl fractions with
ROUNDTRIP cost on traded value.

Inference cost bounds (disclosed proxies, friendly to C by design):
  lower = ~40k tokens/decision observed in metered runs x Rs9/1K = Rs360/decision
  upper = SESSION_TOKEN_CAP 120k tokens x Rs9/1K = Rs1,080/decision

VERDICT RULES (frozen before seeing results — code decides, not preference):
  C_total <= A_total            -> OFF (no incremental value before costs)
  0 < C-A <= lower-bound cost   -> OFF (margin below inference cost)
  C-A > lower-bound cost        -> CONDITIONAL-ON (forward confirmation required;
                                   config stays OFF until forward evidence promotes)
Production default is LLM_OVERLAY_ENABLED=false regardless; only a forward
promotion under GATESET_V1 could change it (R5: code cannot promote itself,
and this script does not change config).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.overlay import apply_llm_overlay, llm_overlay_size, veto_fraction  # noqa: E402
from app.data.base import ROUNDTRIP_COST  # noqa: E402

CAPITAL = 5000000.0
CORE_SIZE = 0.05
TOKEN_RATE_RS_PER_1K = 9.0
COST_LOWER_RS = 40000 * TOKEN_RATE_RS_PER_1K / 1000.0  # Rs360/decision
COST_UPPER_RS = 120000 * TOKEN_RATE_RS_PER_1K / 1000.0  # Rs1,080/decision


def scenario_pnl(size: float, fwd: float) -> float:
    if size <= 0:
        return 0.0
    return size * fwd - size * ROUNDTRIP_COST


def run_books(scenarios: list[dict], capital: float = CAPITAL) -> dict:
    """Compound A (core-long) and C (core + cached LLM overlay) books."""
    book_a = book_c = capital
    n_veto = n_resize = n_pass = 0
    for s in sorted(scenarios, key=lambda r: (r["as_of"], r["instrument"])):
        fwd = float(s["fwd_ret"])
        book_a *= 1.0 + scenario_pnl(CORE_SIZE, fwd)
        final = llm_overlay_size(CORE_SIZE, "long", s["action"], float(s["size"]))
        book_c *= 1.0 + scenario_pnl(final, fwd)
        if final == 0.0 and CORE_SIZE > 0 and s["action"] != "hold":
            n_veto += 1
        elif 0.0 < final < CORE_SIZE:
            n_resize += 1
        else:
            n_pass += 1
    return {"n": len(scenarios), "A_final": round(book_a, 2),
            "C_final": round(book_c, 2),
            "A_profit": round(book_a - capital, 2),
            "C_profit": round(book_c - capital, 2),
            "C_minus_A": round(book_c - book_a, 2),
            "n_veto": n_veto, "n_resize": n_resize, "n_pass": n_pass}


def verdict(books: dict) -> dict:
    margin, n = books["C_minus_A"], books["n"]
    lower, upper = n * COST_LOWER_RS, n * COST_UPPER_RS
    if margin <= 0:
        v = "OFF"
        why = "C adds no incremental value even before inference cost"
    elif margin <= lower:
        v = "OFF"
        why = (f"C-A margin Rs{margin:,.0f} below friendly inference bound "
               f"Rs{lower:,.0f} ({n} decisions x Rs{COST_LOWER_RS:,.0f})")
    else:
        v = "CONDITIONAL-ON"
        why = (f"C-A margin Rs{margin:,.0f} clears Rs{lower:,.0f}; forward confirmation "
               "required, config stays OFF until a GATESET_V1 forward promotion")
    return {"verdict": v, "why": why, "cost_lower_rs": round(lower, 2),
            "cost_upper_rs": round(upper, 2), "config_change": "none (stays OFF)"}


def load_cached_scenarios() -> tuple[list[dict], list[str]]:
    """All stored eval decisions except explicitly quarantined files."""
    scenarios, files = [], []
    for path in sorted(glob.glob(os.path.join("data", "eval_report_*.json"))):
        if "DO_NOT_USE" in path or "oracle_tainted" in path:
            continue
        with open(path, encoding="utf-8") as f:
            rep = json.load(f)
        rows = rep.get("results") or []
        for r in rows:
            if r.get("action") not in ("buy", "sell", "hold"):
                continue
            try:
                scenarios.append({"as_of": r["as_of"], "instrument": r["instrument"],
                                  "action": r["action"], "size": float(r.get("size", 0.0)),
                                  "fwd_ret": float(r["fwd_ret"]),
                                  "source": os.path.basename(path)})
            except (KeyError, TypeError, ValueError):
                continue
        files.append(os.path.basename(path))
    return scenarios, files


def deterministic_check() -> dict:
    """Arm B operator sanity on constructed cases (no history): blowoff vetoed,
    normal flow passes, agreement resizes down — via the tagged production switch."""
    core = {"BLOWOFF.NS": 0.05, "NORMAL.NS": 0.05, "AGREE.NS": 0.05}
    assert veto_fraction("CALM", 0.5, 12.0, 0.1) == 1.0  # blowoff table veto
    views = {"BLOWOFF.NS": {"action": "buy", "size": 0.05, "core_direction": "long"},
             "AGREE.NS": {"action": "buy", "size": 0.02, "core_direction": "long"}}
    finals, rep = apply_llm_overlay(core, views, enabled=True,
                                    experimental_tag="ablation-B-operator-check")
    assert finals["BLOWOFF.NS"] == 0.05  # LLM agrees; det veto is separate layer
    assert finals["AGREE.NS"] == 0.02 and finals["NORMAL.NS"] == 0.05
    off, _ = apply_llm_overlay(core, views, enabled=False)
    assert off == core
    return {"operator_ok": True, "report": rep}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=CAPITAL)
    a = ap.parse_args()
    scenarios, files = load_cached_scenarios()
    books = run_books(scenarios, a.capital)
    books["capital"] = a.capital
    v = verdict(books)
    det = deterministic_check()
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "arms": {"A": "deterministic core-long 0.05 (no overlay)",
                 "B": "core + deterministic veto (synthetic operator check)",
                 "C": "core + cached-LLM overlay via llm_overlay_size (veto/resize only)"},
        "n_scenarios": books["n"], "source_files": files,
        "comparability": ("labels predate the split-adjust fix in some reports "
                          "(see retry notes); as-is, zero new tokens spent"),
        "books": books, "verdict": v, "deterministic_B": det,
        "config": "LLM_OVERLAY_ENABLED=false (unchanged)",
    }
    path = os.path.join("data", "overlay_ablation_20261010.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(json.dumps({**books, **v}, indent=2))
    print("artifact:", path)


if __name__ == "__main__":
    main()
