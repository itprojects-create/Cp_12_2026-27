"""W4 Arm-A integrity check: recompute the frozen W3 feature/label hashes with
the Jev/Mercury plane present but OFF, proving the W4 integration cannot and
did not perturb the W3 numeric control.

Reproduces EXACTLY the W3 snapshot + label build from scripts/wave3_run_quantlab.py
(same cadence, same decision timestamps, same label engine, same hashing) and
skips folds/model fitting entirely. No events_ai import touches this path.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.quantlab import (
    FeaturePanel, build_label, set_session_index)
from quantplus_intelligence.research_v3.quantlab.contracts import ADMISSIBLE

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "alpha_v3_1"
DB = ROOT / "backend-extension" / "data" / "research_v3" / "warehouse.sqlite3"
assert DB.is_file(), f"warehouse missing: {DB}"

TRAIN_START, TRAIN_END = "2015-06-01", "2021-12-31"
VAL_START, VAL_END = "2022-01-01", "2023-12-31"
CAPITAL_PAISE = 10_000_000
T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def _decision_ts(session: str) -> str:
    d = date.fromisoformat(session[:10]) + timedelta(days=1)
    return f"{d.isoformat()}T00:15:00+05:30"


def weekly_sessions(sessions: list[str]) -> list[str]:
    out: dict[tuple[int, int], str] = {}
    for s in sessions:
        if not (TRAIN_START <= s <= VAL_END):
            continue
        d = date.fromisoformat(s[:10])
        out[(d.isocalendar().year, d.isocalendar().week)] = s
    return [out[k] for k in sorted(out)]


def monthly_sessions(sessions: list[str]) -> list[str]:
    out: dict[str, str] = {}
    for s in sessions:
        if not (TRAIN_START <= s <= VAL_END):
            continue
        out[s[:7]] = s
    return [out[k] for k in sorted(out)]


def _members(panel: FeaturePanel, session: str) -> tuple[list[str], int]:
    res = W.members_at(panel.conn, "nifty50", session)
    names = [m for m in res.rows if panel.key_for(m)]
    return names, len(res.rows) - len(names)


def _hash_labels(labels_ic) -> str:
    from quantplus_intelligence.research_v3.lab.spec import fingerprint
    core = sorted((sym, session, h,
                   l.admissibility, l.status,
                   None if l.gross_return is None else round(l.gross_return, 12),
                   l.exit_session)
                  for (sym, session, h), l in labels_ic.items())
    return fingerprint({"labels": core})


def _hash_features(snaps, feature_names) -> str:
    from quantplus_intelligence.research_v3.lab.spec import fingerprint
    core = sorted((sym, session,
                   {k: round(snap.features[k], 12) for k in feature_names
                    if k in snap.features})
                  for (sym, session), snap in snaps.items())
    return fingerprint({"features": core})


def main() -> None:
    contracts = json.loads((REPORTS / "wave3_feature_label_contracts.json")
                           .read_text(encoding="utf-8"))
    conn = W.connect(str(DB))
    panel = FeaturePanel(conn, "nifty50")
    set_session_index(panel.sessions)
    log(f"panel built: {len(panel.series)} spell symbols, {len(panel.sessions)} sessions")

    wk = weekly_sessions(panel.sessions)
    mo = monthly_sessions(panel.sessions)
    log(f"decision cadence: weekly={len(wk)} monthly={len(mo)}")

    snaps: dict[tuple[str, str], object] = {}
    excluded_unknown = 0
    for cadence, sessions in (("weekly", wk), ("monthly", mo)):
        for session in sessions:
            members, unknown = _members(panel, session)
            excluded_unknown += unknown
            dts = _decision_ts(session)
            for name in members:
                snaps[(name, session)] = panel.snapshot(name, dts, name)
    log(f"snapshots: {len(snaps)} (universe names without panel bars: {excluded_unknown})")

    labels_ic: dict[tuple[str, str, int], object] = {}
    tasks: list[tuple[str, str, int]] = []
    for (name, session) in snaps:
        if session in wk:
            tasks.append((name, session, 5))
            tasks.append((name, session, 20))
        if session in mo:
            tasks.append((name, session, 60))
    done = 0
    for name, session, h in tasks:
        labels_ic[(name, session, h)] = build_label(
            panel, name, _decision_ts(session), h, exit_ref="CLOSE",
            notional_paise=CAPITAL_PAISE)
        done += 1
        if done % 10000 == 0:
            log(f"  labels {done}/{len(tasks)}")
    admissible = sum(1 for l in labels_ic.values() if l.admissibility == ADMISSIBLE)
    blocked = sum(1 for l in labels_ic.values()
                  if l.admissibility == "DATA_BLOCKED_ACTION_WINDOW")
    nolabel = sum(1 for l in labels_ic.values() if l.admissibility == "NO_LABEL")
    log(f"labels: {len(labels_ic)} total; admissible={admissible} "
        f"data_blocked_action={blocked} no_label={nolabel}")

    label_hash = _hash_labels(labels_ic)
    feature_names = ("ret_20", "ret_60", "prox_252", "vol_20",
                     "trend_consistency_20", "volume_ratio_20", "liquidity_20",
                     "drawdown_60", "overnight_gap", "rel_mom_60")
    feature_hash = _hash_features(snaps, feature_names)

    ok_features = feature_hash == contracts["feature_hash"]
    ok_labels = label_hash == contracts["label_hash"]
    counts_match = (len(labels_ic) == 49989 and admissible == 47852
                    and blocked == 163 and nolabel == 1974)
    result = {
        "check": "wave4_arm_a_frozen_w3_control",
        "feature_hash_recomputed": feature_hash,
        "feature_hash_frozen": contracts["feature_hash"],
        "feature_hash_match": ok_features,
        "label_hash_recomputed": label_hash,
        "label_hash_frozen": contracts["label_hash"],
        "label_hash_match": ok_labels,
        "label_counts": {"total": len(labels_ic), "admissible": admissible,
                         "data_blocked_action_window": blocked, "no_label": nolabel},
        "label_counts_match_frozen": counts_match,
        "jev_state": "OFF (events_ai never imported on this path)",
        "verdict": "UNCHANGED" if (ok_features and ok_labels and counts_match) else "DRIFT",
    }
    out = REPORTS / "wave4_w3_control_reevaluation.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    log(f"feature_hash match: {ok_features}")
    log(f"label_hash match: {ok_labels}")
    log(f"label counts match: {counts_match}")
    log(f"verdict: {result['verdict']} -> {out}")


if __name__ == "__main__":
    main()
