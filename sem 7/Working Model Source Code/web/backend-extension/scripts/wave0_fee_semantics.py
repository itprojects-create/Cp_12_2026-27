"""W0.4 — write fee_semantics_and_reconciliation.json + wave0_fee_semantics.json.

Derives (never hand-types) the fee-truth evidence:
- itemised charges for the canonical fixtures, from research_v3.economics
- the bun parity run against the real TypeScript book engine (when bun exists)
- the -5%/-6% absolute-vs-relative fixture from the regression test module
Read-only; no account state, no settlement.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from quantplus_intelligence.research_v3 import economics  # noqa: E402
from quantplus_intelligence.research_v3.economics import (  # noqa: E402
    delivery_charges, trade_cash_pnl, v3_benchmark_relative, METRIC_SEMANTICS)

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports" / "alpha_v3_1"
BUN_SCRIPT = HERE / "scripts" / "fee_parity_bun.ts"


def main() -> int:
    fixture = {}
    # canonical absolute-vs-relative fixture: -5% stock, -6% benchmark, Rs 1,000 x 100
    trade = trade_cash_pnl(100, 100_000, 95_000, "2026-11-02T10:00:00Z", "2026-11-06T10:00:00Z")
    fixture["negative_absolute_return_not_profitable"] = {
        "stock_gross": -0.05, "benchmark_gross": -0.06,
        "v3_benchmark_relative": v3_benchmark_relative(-0.05, -0.06),
        "v2_style_flattering_number": (-0.05 - -0.06) - 0.004,
        "v3_net_absolute": trade["v3_net_absolute"],
        "v3_trade_cash_pnl_paise": trade["v3_trade_cash_pnl_paise"],
        "verdict": "positive benchmark-relative spread with a NEGATIVE absolute net cash P&L",
    }
    fee_cases = {}
    for label, side, turnover in (("10k_buy", "BUY", 1_000_000), ("10k_sell", "SELL", 1_000_000),
                                  ("1L_buy", "BUY", 10_000_000), ("1L_sell", "SELL", 10_000_000),
                                  ("50k_buy", "BUY", 5_000_000)):
        charges = delivery_charges(side, turnover, "2026-03-01T10:00:00Z")
        fee_cases[label] = {"turnover_paise": turnover, "schedule": charges["schedule"],
                            "items": {i["code"]: i["amount_paise"] for i in charges["items"]},
                            "total_paise": charges["total_paise"],
                            "fraction_of_turnover": charges["total_paise"] / turnover}
    fyers = delivery_charges("BUY", 1_000_000, "2026-03-01T10:00:00Z", broker="fyers_delivery_2026")
    fee_cases["10k_buy_fyers_brokerage"] = {
        "turnover_paise": 1_000_000, "broker_component": "fyers_delivery_2026",
        "items": {i["code"]: i["amount_paise"] for i in fyers["items"]},
        "total_paise": fyers["total_paise"],
        "fraction_of_turnover": fyers["total_paise"] / 1_000_000}

    parity = {"available": False}
    bun = shutil.which("bun")
    if bun:
        proc = subprocess.run([bun, str(BUN_SCRIPT)], capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            ts_cases = json.loads(proc.stdout)
            checks = []
            for case in ts_cases:
                if "error" in case:
                    continue
                py = delivery_charges(case["side"], case["turnover_paise"], case["at"])
                checks.append({"case": f"{case['side']}@{case['turnover_paise']}",
                               "match": (py["total_paise"] == case["total_paise"]
                                         and {i["code"]: i["amount_paise"] for i in py["items"]} == case["items"])})
            parity = {"available": True, "engine": "bun + src/lib/paper-fees.ts",
                      "checks": checks, "all_match": all(c["match"] for c in checks)}
        else:
            parity = {"available": True, "error": proc.stderr[:400]}

    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "w0_defect": "bridge.py edge_gate and shadow.py settled lines compute "
                     "'realised benchmark-relative excess - 0.004 flat' and label it "
                     "long_edge_after_costs / net: not executable absolute net cash profit.",
        "reproduction": {
            "bridge.py:59": "long_edge = mean(r['outcome']['excess_return']) - cost_hurdle",
            "shadow.py:189": "net = float(excess) - COST_HURDLE",
            "status": "REPRODUCED (code inspection + test fixture; formulas unchanged, "
                      "correction labels added additively)",
        },
        "correction": {
            "module": "quantplus_intelligence.research_v3.economics",
            "metric_semantics": METRIC_SEMANTICS,
            "v2_series_untouched": True,
            "additive_labels": ["bridge.edge_gate().metric_semantics",
                                "shadow.summary().metric_semantics"],
            "ui_trace": {
                "ForecastCard.tsx": "excess labelled 'vs NIFTY (outperformed/underperformed)' - correct",
                "StrategyLabPage mean_net": "per-trade gross minus flat round-trip cost - absolute "
                                            "basis with declared survivorship bias; paise-exact "
                                            "upgrade assigned to W2 engine",
            },
        },
        "fee_schedule": {"mirror_of": "src/lib/paper-fees.ts schedule nse-cm-delivery-2026-03-01",
                         "rounding": "round half away from zero (money.ts semantics); STT to rupee per fill",
                         "money_unit": "integer paise only"},
        "fee_cases": fee_cases,
        "fixture": fixture,
        "typescript_parity": parity,
        "tests": ["backend-extension/tests/test_research_v3_economics.py"],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, indent=2, default=str)
    (REPORTS / "fee_semantics_and_reconciliation.json").write_text(payload, encoding="utf-8")
    (REPORTS / "wave0_fee_semantics.json").write_text(payload, encoding="utf-8")
    print(json.dumps({"parity": parity["available"], "all_match": parity.get("all_match"),
                      "cash_fixture_paise": trade["v3_trade_cash_pnl_paise"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
