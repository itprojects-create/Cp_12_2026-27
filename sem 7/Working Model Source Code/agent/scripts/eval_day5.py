"""Day-5 biting eval assembly (prereg_day5_eval.md Gate). As-is report, no re-runs on miss.

- Narrow DSR: recomputes frozen v4 narrow (measurement re-run, preregistered)
  capturing eq_curve -> daily moments -> DSR with K=10 trials.
- Overlay 0.776 DSR uses narrow moments as labeled APPROXIMATE proxy.
- Broad DSR: PENDING (no 391-name refetch today) — stated, not hidden.
- Perturbation suite, friction matrix, ablation statuses included.
Zero LLM tokens (Devil-off ablation stays QUEUED — needs funded gateway).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.trend_core import UNIVERSE as NIFTY50, INDEX_TICKER  # noqa: E402
from app.core.trend_core_v4 import run_core_v4  # noqa: E402
from app.core.overlay import apply_veto, veto_fraction  # noqa: E402
from app.data.positioning import positioning_veto_fraction  # noqa: E402
from app.eval import dsr as D  # noqa: E402
from app.eval import friction as FR  # noqa: E402
from app.eval import perturb as PZ  # noqa: E402

START, END = "2021-01-01", "2026-10-01"


def _single(ticker: str):
    df = yf.download(ticker, start=START, end=END, interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return [float(x) for x in df["Close"].dropna().tolist()]


def main() -> None:
    idx = _single(INDEX_TICKER)
    n = len(idx)
    try:
        vix = _single("^INDIAVIX")
        vix = (vix + [vix[-1]] * n)[:n] if len(vix) != n else vix
    except Exception as e:
        print(f"WARN: VIX failed ({e}); CALM fallback")
        vix = None
    names, excluded = {}, []
    for t in NIFTY50:
        try:
            cs = _single(t)
        except Exception:
            excluded.append(t)
            continue
        if not cs:
            excluded.append(t)
            continue
        names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
    rep = run_core_v4(idx, names, vix_closes=vix)
    eq = rep.eq_curve
    daily = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    mom = D.moments(daily)
    sharpes = [s for _, s, _ in D.TRIALS]
    narrow_dsr = D.dsr(rep.sharpe, len(daily), mom["skew"], mom["kurtosis"], sharpes)
    over = json.load(open("data/overlay_vs_core_20261007.json", encoding="utf-8"))
    overlay_dsr = D.dsr(over["overlay"]["sharpe"], len(daily), mom["skew"],
                        mom["kurtosis"], sharpes)

    rows = [{"ret_5d": -10 + i * 0.8, "dist_hi": -15 + i * 0.6,
             "blackout": (i % 7 == 0)} for i in range(40)]
    pert = {
        "veto_CALM_wide": PZ.suite(PZ.veto_row_fn(veto_fraction, "CALM", 0.7), rows),
        "veto_STRESSED_narrow": PZ.suite(PZ.veto_row_fn(veto_fraction, "STRESSED", 0.3), rows),
        "positioning": PZ.suite(
            lambda r: positioning_veto_fraction(r["ret_5d"] / 10, r["dist_hi"] > -2, None)[0],
            [{"ret_5d": -10 + i * 0.8, "dist_hi": -15 + i * 0.6} for i in range(40)]),
        "apply_veto": PZ.suite(
            lambda r: apply_veto({"A": 0.08}, {"A": min(1.0, max(0.0, r["ret_5d"] / 100))})["A"],
            [{"ret_5d": -10 + i * 0.8} for i in range(40)]),
    }
    out = {
        "prereg": "data/prereg_day5_eval.md",
        "trials": [{"name": nm, "sharpe": s, "artifact": a} for nm, s, a in D.TRIALS],
        "narrow_recompute": {"n_names": len(names), "n_excluded": len(excluded),
                             "sharpe": round(rep.sharpe, 3),
                             "skew": round(mom["skew"], 3),
                             "kurtosis": round(mom["kurtosis"], 3),
                             "t_obs": len(daily)},
        "dsr_narrow_v4": narrow_dsr,
        "dsr_overlay_proxy_APPROXIMATE": dict(overlay_dsr,
            note="uses v4-narrow moments as proxy; overlay curve moments not persisted"),
        "dsr_broad": {"status": "PENDING",
                       "reason": "needs 391-name daily recompute; K=10 trial bar applies a fortiori"},
        "perturbation": pert,
        "perturbation_gates": {k: {"pc_gate": v["pc_gate"], "ids_gate": v["ids_gate"]}
                               for k, v in pert.items()},
        "friction": FR.matrix(),
        "friction_counts": FR.modeled_count(),
        "ablations": {
            "veto_off_vs_on": {"status": "CITED",
                "source": "data/overlay_vs_core_20261007.json",
                "off_sharpe": over["core_v3"]["sharpe"],
                "on_sharpe": over["overlay"]["sharpe"]},
            "devil_off": {"status": "QUEUED",
                "command": "python scripts/ablate_devil.py --set v1 --bill",
                "blocked_on": "funded gateway (day cap exhausted during Day-5 window)"},
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join("data", f"eval_day5_biting_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("trials", "friction", "perturbation")}, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
