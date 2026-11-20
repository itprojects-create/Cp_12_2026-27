"""Recompute broad-core DSR deterministically (P5, §52). Zero LLM tokens.

Rebuilds the broad 2021-2026 daily series with the frozen v4 rule (same fetch
pattern as run_core_backtest_v4 --universe broad), takes moments over the
strategy's own daily net returns, and scores DSR against the persistent
multiple-testing ledger (seeded if empty). Writes the §55 broad verdict block:
historical, PIT-corrected (from the existing pit500 diagnostic artifact),
DSR, concentration (from the verification audit), beta (from overlay compare),
forward status — each labeled with its source, never collapsed into one label.

Usage: python scripts/recompute_broad_dsr.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "scripts")

from run_core_backtest_v4 import _batch, _single  # noqa: E402

from app.core.trend_core import INDEX_TICKER  # noqa: E402
from app.core.trend_core_v4 import run_core_v4  # noqa: E402
from app.eval import dsr as DSR  # noqa: E402
from app.eval import trials as TR  # noqa: E402


def main() -> None:
    idx, _ = _single(INDEX_TICKER)
    n = len(idx)
    try:
        vix = _single("^INDIAVIX")[0]
        vix = (vix + [vix[-1]] * n)[:n] if len(vix) != n else vix
    except Exception as e:
        print(f"WARN: VIX failed ({e}); CALM fallback")
        vix = None
    with open("data/nifty500.txt", encoding="utf-8-sig") as f:
        want = [line.strip().upper() for line in f if line.strip()]
    with open("data/nifty500_sectors.json", encoding="utf-8-sig") as f:
        secmap = json.load(f)
    from app.core.trend_core import UNIVERSE as NIFTY50
    got = _batch(sorted(set(want)))
    names, excluded = {}, []
    for t, cs in got.items():
        if not cs or len(cs) < n * 0.9:
            excluded.append(t)
            continue
        names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
    tier = {t: ("nifty50" if t in NIFTY50 else "nifty500") for t in names}
    sector = {t: secmap.get(t, "UNKNOWN") for t in names}
    print(f"bars={n} names={len(names)} excluded={len(excluded)}")

    rep = run_core_v4(idx, names, vix_closes=vix, tier=tier, sector=sector)
    eq = rep.eq_curve
    daily = [eq[i] / eq[i - 1] - 1 if eq[i - 1] else 0.0 for i in range(1, len(eq))]
    mom = DSR.moments(daily)

    seed = TR.seed_historical()
    trial_id = "broad-dsr-20261010"
    TR.record_trial(trial_id, "return", round(rep.sharpe, 3),
                    outcome="DSR_RECOMPUTE", status="done",
                    note="broad v4 2021-2026 deterministic recompute (P5)")
    report = TR.dsr_report("v4-broad", "strat-v4-broad-frozen", "2021-01-01..2026-10-01",
                           round(rep.sharpe, 3), len(daily),
                           mom["skew"], mom["kurtosis"])

    hist = json.load(open("data/core_backtest_v4_broad.json", encoding="utf-8"))
    pit = json.load(open("data/core_backtest_v4_pit500.json", encoding="utf-8"))
    verdict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "historical_performance": {
            "source": "data/core_backtest_v4_broad.json (prior artifact, as-is)",
            "cagr": hist.get("cagr"), "sharpe": hist.get("sharpe"),
            "max_drawdown": hist.get("max_drawdown")},
        "pit_corrected_performance": {
            "source": "data/core_backtest_v4_pit500.json (start-date PIT diagnostic)",
            "cagr": pit.get("cagr"), "sharpe": pit.get("sharpe"),
            "max_drawdown": pit.get("max_drawdown"),
            "note": "start-date snapshot only; per-rebalance P0 layer now available"},
        "dsr": report,
        "ledger": seed,
        "concentration_dependence": {
            "source": "verification audit (as-is)",
            "note": "2022 broad green carried by 5 names (FACT 68% of net); "
                    "~95% of return approx half-beta exposure"},
        "beta_attribution": {
            "source": "data/overlay_vs_core_20261007.json + blind 2015-2020 PASS",
            "note": "no fresh beta regression in this recompute; see prior artifacts"},
        "forward_status": "INFANCY — forward clock owns promotion evidence (R8)",
    }
    path = os.path.join("data", "broad_dsr_20261010.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2)
    print(json.dumps({k: verdict[k] for k in ("dsr", "ledger", "forward_status")}, indent=2))
    print("artifact:", path)


if __name__ == "__main__":
    main()
