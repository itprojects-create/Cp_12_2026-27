"""Self-contained HTML report (Day 5, NEW_PLAN). No JS, no external assets.

Renders core v2 vs v3 + overlay prereg + eval honesty summary as one page for
the Monday demo (frontend itself is already built separately).
Usage: python scripts/render_report.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str) -> dict:
    p = os.path.join(ROOT, "data", name)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    v2 = _load("core_backtest_20261006.json")
    v3 = _load("core_backtest_v3.json")
    rows = ""
    for label, d in (("Core v2 (frozen, GROSS_CAP=1.00)", v2), ("Core v3 (VIX+turnover+vol-target)", v3)):
        if not d:
            continue
        rows += (f"<tr><td>{label}</td><td>{d.get('cagr','?')}</td><td>{d.get('sharpe','?')}</td>"
                 f"<td>{d.get('max_drawdown','?')}</td><td>{d.get('avg_exposure','?')}</td>"
                 f"<td>{d.get('total_cost','?')}</td><td>{d.get('n_switches','?')}</td></tr>")
    y2022 = ""
    for label, d in (("v2", v2), ("v3", v3)):
        yd = (d.get("yearly_diagnostic") or {}).get("2022", {})
        y2022 += f"<li>{label} 2022: {yd.get('ret','?')} (intra-dd {yd.get('intra_yr_dd','?')})</li>"
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>QuantPlus — Core v2 vs v3 + Honesty Report</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#111}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.4rem .6rem;text-align:right}}
td:first-child,th:first-child{{text-align:left}}.good{{color:#0a6b0a}}.bad{{color:#a00}}</style>
</head><body>
<h1>QuantPlus Agentic OS — Profit Baseline + Honest Eval</h1>
<p>Generated {datetime.now(timezone.utc).isoformat()} · Costs 0.21% round-trip · PIT-enforced · Gates frozen 2026-09-18</p>
<h2>Core backtest (2021-2026, same window, zero tokens)</h2>
<table><tr><th>Rule</th><th>CAGR</th><th>Sharpe</th><th>MaxDD</th><th>Exposure</th><th>Costs</th><th>Switches</th></tr>
{rows}</table>
<h3>Whipsaw check (2022)</h3><ul>{y2022}</ul>
<p>v3 gate: MaxDD&lt;16.35% OR Sharpe&gt;0.698 AND 2022&gt;-10.25%. v2 file untouched; v3 in <code>app/core/trend_core_v3.py</code> (prereg <code>data/prereg_core_v3.md</code>).</p>
<h2>LLM direction: 13 FAILs, honestly recorded</h2>
<p>Agent selection never beats the best constant rule (11/11 + H1 0.111 vs 0.556). Per prereg rule the LLM never picks direction on the money path — veto/resize only (overlay contract <code>data/prereg_overlay_retry.md</code>), or explainability-only on FAIL.</p>
<h2>What beats TradingAgents here</h2>
<ul><li>PIT enforced in code + tested (prefix-invariance, gross-cap, cost bounds)</li>
<li>Cost-realistic paper fills + turnover-aware core (switches 3968→1081, costs 6.4%→3.5%)</li>
<li>Frozen gates + beats-best-constant + binomial anchor (no goalpost moves)</li>
<li>Versioned thesis HEALTHY→BROKEN + settle/reflect memory (PIT-clean lessons)</li>
<li>Portfolio-aware sizing + 5-tier + REVIEW + India moat (delivery, VIX, earnings blackout, AngelOne paper next)</li></ul>
</body></html>"""
    out = os.path.join(ROOT, "data", "complete_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("report:", out)


if __name__ == "__main__":
    main()
