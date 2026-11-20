"""One-shot retry-m10 eval on the v3rd 2026 set (prereg data/prereg_overlay_retry.md).

Mirrors app/eval/run.py scoring EXACTLY (same forward_return/labels/costs/gates/
baselines) — the only difference is the decision path: run_session_retry with
`cfg|retry` sid namespace + `retry_*` checkpoints, so no frozen-pipeline session
is ever reused. Reruns resume cached-done retry sessions without re-billing.
Recorded as-is (PASS or FAIL). Strict gate vs overlay applies at analysis time.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import schemas as S  # noqa: E402
from app.agents import graph as G  # noqa: E402
from app.agents import retry_manager as R  # noqa: E402
from app.api.v1 import _cfg_hash  # noqa: E402
from app.db import sqlite_conn  # noqa: E402
from app.eval.run import forward_return, label_of, direction_sign, summarize  # noqa: E402
from app.eval.scenarios_v3rd import SCENARIOS_V3RD, SET_NAME  # noqa: E402
from app.data.base import ROUNDTRIP_COST  # noqa: E402
from app.gateway.codecraft import gateway  # noqa: E402


def run_eval_retry() -> dict:
    results = []
    cfg = _cfg_hash() + "|retry"
    for i, (instrument, day) in enumerate(SCENARIOS_V3RD):
        as_of = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        sid = G.new_session_id(instrument, as_of.isoformat(), cfg)
        conn = sqlite_conn()
        if not conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
            conn.execute(
                "INSERT INTO sessions(id, instrument, as_of, config_hash, status, decision) VALUES (?,?,?,?,?,?)",
                (sid, instrument, as_of.isoformat(), cfg, "queued", None))
            conn.commit()
        row = conn.execute("SELECT status, decision FROM sessions WHERE id=?", (sid,)).fetchone()
        if row[0] == "done" and row[1]:
            dec = S.FinalDecision(**json.loads(row[1]))
            resumed = True
        else:
            dec = R.run_session_retry(sid, instrument, as_of, "1d")
            resumed = False
        fwd = forward_return(instrument, as_of)
        label = label_of(fwd)
        direction = {"buy": "long", "sell": "short", "hold": "flat"}[dec.action]
        correct = direction == label
        traded = 1 if dec.action != "hold" else 0
        pnl = direction_sign(dec.action) * dec.size * fwd - traded * dec.size * ROUNDTRIP_COST
        thesis = (G.thesis_history(instrument) or [{}])[-1]
        results.append({"instrument": instrument, "as_of": day, "session": sid, "resumed": resumed,
                        "fwd_ret": round(fwd, 4), "label": label, "action": dec.action,
                        "size": dec.size, "correct": correct, "pnl": round(pnl, 5),
                        "thesis_status": thesis.get("status")})
        mark = "CACHED" if resumed else ("OK " if correct else "MISS")
        print(f"[{i + 1:2d}/{len(SCENARIOS_V3RD)}] {instrument:14s} {day} action={dec.action:4s} "
              f"label={label:5s} {mark} tokens={gateway.day_usage}", flush=True)
    report = summarize(results)
    report["scenario_set"] = SET_NAME + "+retry-m10"
    report["manager_mode"] = "retry"
    return report


if __name__ == "__main__":
    from app.config import settings as _s
    print("gates frozen:", __import__("app.eval.gates", fromlist=["FROZEN_DATE"]).FROZEN_DATE, flush=True)
    print("manager_mode=retry, prompt:", _s.PROMPT_VERSION, flush=True)
    report = run_eval_retry()
    report["notes"] = ("One-shot retry-m10 eval (prereg data/prereg_overlay_retry.md). "
                       "Labels use split-adjusted forward returns (Day 1 fix); "
                       "not strictly comparable to pre-20261007 reports. As-is.")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join("data", f"eval_report_retry_{ts}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("SUMMARY:", json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    print("report:", out, "| day tokens used:", gateway.day_usage)
