"""Run the live 24-scenario eval ONCE and record the honest report.

Sessions cache by deterministic id: interrupting + rerunning resumes without re-billing.
Gates were frozen in app/eval/gates.py BEFORE this script's first run — whatever the
verdict (including FAIL), it is recorded as-is.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.eval.run import run_eval, V5_SET_NAME
from app.eval.scenarios_v5 import SCENARIOS_V5
from app.eval.scenarios_v3rd import SCENARIOS_V3RD, SET_NAME as V3RD_SET_NAME
from app.eval.scenarios_v4 import SCENARIOS_V4, SET_NAME as V4_SET_NAME
from app.eval.scenarios_v6 import SCENARIOS_V6, SET_NAME as V6_SET_NAME
from app.eval.scenarios_v7 import SCENARIOS_V7, SET_NAME as V7_SET_NAME
from app.gateway.codecraft import gateway

def progress(i, n, inst, day, action, label, correct, resumed):
    mark = "CACHED" if resumed else ("OK " if correct else "MISS")
    print(f"[{i:2d}/{n}] {inst:14s} {day} action={action:4s} label={label:5s} {mark} "
          f"tokens={gateway.day_usage}", flush=True)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["v1", "v5", "v3", "v4", "v6", "v7"], default="v1",
                    help="v1 = original 24; v5 = disjoint 2025 set; "
                         "v3 = clean 2026 third set; v4 = fresh blind 2022 set (H1 test); "
                         "v6 = unburned 2026 H2 set; v7 = fresh unburned 2026 H2 set")
    args = ap.parse_args()
    scenarios, set_name = ((SCENARIOS_V3RD, V3RD_SET_NAME) if args.set == "v3"
                             else (SCENARIOS_V4, V4_SET_NAME) if args.set == "v4"
                             else (SCENARIOS_V6, V6_SET_NAME) if args.set == "v6"
                             else (SCENARIOS_V7, V7_SET_NAME) if args.set == "v7"
                             else (SCENARIOS_V5, V5_SET_NAME) if args.set == "v5"
                             else (None, "v1-2023-2024"))
    print("gates frozen:", __import__("app.eval.gates", fromlist=["FROZEN_DATE"]).FROZEN_DATE, flush=True)
    print("scenario set:", set_name, flush=True)
    report = run_eval(on_progress=progress, scenarios=scenarios, set_name=set_name)
    from app.config import settings as _s
    report["notes"] = (f"Official one-shot run on prompt {_s.PROMPT_VERSION}, scenario set {set_name}. "
        "Gates unchanged since 2026-09-18 freeze; prompt-versioned session ids supersede "
        "all prior pilots. Whatever the verdict, it is recorded as-is.")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join("data", f"eval_report_{ts}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    s = {k: v for k, v in report.items() if k != "results"}
    print("SUMMARY:", json.dumps(s, indent=2))
    print("report:", out, "| day tokens used:", gateway.day_usage)
