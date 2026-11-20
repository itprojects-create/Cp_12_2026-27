"""Devil-off ablation harness (Day-5 prereg §4). QUEUED — not executed without funds.

Mirrors app/eval/run.py scoring exactly, but calls run_session with
devil_mode="off" under a distinct sid namespace ("|deviloff") so ablated
sessions never collide with production cache. Double-gated: default --dry-run
prints the plan and bills nothing; a real run needs --bill AND a funded gateway.

Queued command (funded window):
    python scripts/ablate_devil.py --set v1 --bill
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import schemas as S  # noqa: E402
from app.agents import graph as G  # noqa: E402
from app.api.v1 import _cfg_hash  # noqa: E402
from app.db import sqlite_conn  # noqa: E402
from app.eval.run import (  # noqa: E402
    _ensure_row, direction_sign, forward_return, label_of, summarize,
)
from app.data.base import ROUNDTRIP_COST  # noqa: E402


def ablated_sid(instrument: str, as_of_iso: str) -> str:
    return G.new_session_id(instrument, as_of_iso, _cfg_hash() + "|deviloff")


def run_ablation(scenarios: list, set_name: str, on_progress=None) -> dict:
    from app.gateway.codecraft import gateway  # noqa: E402
    results = []
    for i, (instrument, day) in enumerate(scenarios):
        as_of = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        sid = ablated_sid(instrument, as_of.isoformat())
        _ensure_row(sid, instrument, as_of)
        row = sqlite_conn().execute(
            "SELECT status, decision FROM sessions WHERE id=?", (sid,)).fetchone()
        if row[0] == "done" and row[1]:
            dec = S.FinalDecision(**json.loads(row[1]))
            resumed = True
        else:
            dec = G.run_session(sid, instrument, as_of, "1d", devil_mode="off")
            resumed = False
        fwd = forward_return(instrument, as_of)
        label = label_of(fwd)
        direction = {"buy": "long", "sell": "short", "hold": "flat"}[dec.action]
        results.append({"instrument": instrument, "as_of": day, "session": sid,
                        "resumed": resumed, "fwd_ret": round(fwd, 4), "label": label,
                        "action": dec.action, "size": dec.size,
                        "correct": direction == label,
                        "pnl": round(direction_sign(dec.action) * dec.size * fwd
                                     - (1 if dec.action != "hold" else 0)
                                     * dec.size * ROUNDTRIP_COST, 5)})
        if on_progress:
            on_progress(i + 1, len(scenarios), instrument, day, gateway.day_usage)
    report = summarize(results)
    report["scenario_set"] = set_name + "+deviloff"
    report["ablation"] = "devil_mode=off (default HEALTHY, no falsification)"
    return report


if __name__ == "__main__":
    import argparse
    from app.eval.scenarios import SCENARIOS
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="v1")
    ap.add_argument("--bill", action="store_true",
                    help="REQUIRED to spend tokens; without it, dry-run only")
    a = ap.parse_args()
    if not a.bill:
        print(f"DRY-RUN: would run {len(SCENARIOS)} devil-off sessions on set {a.set} "
              f"under sid namespace '|deviloff'. Re-run with --bill on a funded day.")
        sys.exit(0)
    rep = run_ablation(SCENARIOS, "v1-2023-2024",
                       on_progress=lambda i, n, ins, d, t: print(
                           f"[{i}/{n}] {ins} {d} tokens={t}", flush=True))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join("data", f"eval_report_deviloff_{ts}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps({k: v for k, v in rep.items() if k != "results"}, indent=2))
