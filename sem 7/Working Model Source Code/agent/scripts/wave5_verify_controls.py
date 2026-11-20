"""Recompute frozen W3 controls and prove W2-W4 evidence stayed unchanged.

Offline only.  The 1.6 GB warehouse is opened with SQLite ``mode=ro`` and
``query_only=ON``.  No Jev/Mercury module is imported on the numerical path and
no provider call exists in this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab.journal import ResearchJournal
from quantplus_intelligence.research_v3.lab.spec import fingerprint
from quantplus_intelligence.research_v3.quantlab import FeaturePanel, build_label, set_session_index
from quantplus_intelligence.research_v3.quantlab.contracts import ADMISSIBLE


TRAIN_START, VAL_END = "2015-06-01", "2023-12-31"
CAPITAL_PAISE = 10_000_000
PINNED_FILES = {
    "wave2_research_journal.jsonl": "c24c9b0491fa9bbd819b12393ce84a1aa5321f40c35e48d0b3c233986f50c2e7",
    "wave3_research_journal.jsonl": "ab9a77695e87b49960c9086815b3de07a642f9cb15e82e1ba953246aa0f37426",
    "wave3_feature_label_contracts.json": "d637413444e9afe09a705191f05d5e3610fac0d82684c51831a5c42538c9de77",
    "wave4_event_evidence_manifest.json": "f322a7d649bf976b1a6315ec8a12c8b7bf30a5c24e03cefbf4295d31dcefb7d4",
    "wave4_goldset_metrics.json": "a2a49b825071aa71cb0442464520ec968bb79272f08667a6ab92188ad0e549ea",
    "wave4_w3_control_reevaluation.json": "e3f1d782fe2fd4a6cc8e0518d9e63be04a186ef4e72bbeba116b144dc177baeb",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decision_ts(session: str) -> str:
    return f"{(date.fromisoformat(session) + timedelta(days=1)).isoformat()}T00:15:00+05:30"


def weekly_sessions(sessions: list[str]) -> list[str]:
    out: dict[tuple[int, int], str] = {}
    for session in sessions:
        if TRAIN_START <= session <= VAL_END:
            value = date.fromisoformat(session)
            out[(value.isocalendar().year, value.isocalendar().week)] = session
    return [out[key] for key in sorted(out)]


def monthly_sessions(sessions: list[str]) -> list[str]:
    out: dict[str, str] = {}
    for session in sessions:
        if TRAIN_START <= session <= VAL_END:
            out[session[:7]] = session
    return [out[key] for key in sorted(out)]


def members(panel: FeaturePanel, session: str) -> list[str]:
    result = W.members_at(panel.conn, "nifty50", session)
    return [member for member in result.rows if panel.key_for(member)]


def hash_labels(labels) -> str:
    core = sorted((symbol, session, horizon, label.admissibility, label.status,
                   None if label.gross_return is None else round(label.gross_return, 12),
                   label.exit_session)
                  for (symbol, session, horizon), label in labels.items())
    return fingerprint({"labels": core})


def hash_features(snapshots, feature_names) -> str:
    core = sorted((symbol, session,
                   {name: round(snapshot.features[name], 12) for name in feature_names
                    if name in snapshot.features})
                  for (symbol, session), snapshot in snapshots.items())
    return fingerprint({"features": core})


def verify(args) -> dict:
    reports = Path(args.reports).resolve()
    db_path = Path(args.db).resolve()
    contracts = json.loads((reports / "wave3_feature_label_contracts.json")
                           .read_text(encoding="utf-8"))
    uri = "file:" + db_path.as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only=ON")
    panel = FeaturePanel(conn, "nifty50")
    set_session_index(panel.sessions)
    weekly = weekly_sessions(panel.sessions)
    monthly = monthly_sessions(panel.sessions)
    snapshots = {}
    for cadence in (weekly, monthly):
        for session in cadence:
            cutoff = decision_ts(session)
            for symbol in members(panel, session):
                snapshots[(symbol, session)] = panel.snapshot(symbol, cutoff, symbol)
    labels = {}
    tasks = []
    for symbol, session in snapshots:
        if session in weekly:
            tasks.extend(((symbol, session, 5), (symbol, session, 20)))
        if session in monthly:
            tasks.append((symbol, session, 60))
    for symbol, session, horizon in tasks:
        labels[(symbol, session, horizon)] = build_label(
            panel, symbol, decision_ts(session), horizon, exit_ref="CLOSE",
            notional_paise=CAPITAL_PAISE)
    counts = {
        "total": len(labels),
        "admissible": sum(label.admissibility == ADMISSIBLE for label in labels.values()),
        "data_blocked_action_window": sum(
            label.admissibility == "DATA_BLOCKED_ACTION_WINDOW" for label in labels.values()),
        "no_label": sum(label.admissibility == "NO_LABEL" for label in labels.values()),
    }
    feature_names = ("ret_20", "ret_60", "prox_252", "vol_20",
                     "trend_consistency_20", "volume_ratio_20", "liquidity_20",
                     "drawdown_60", "overnight_gap", "rel_mom_60")
    feature_hash = hash_features(snapshots, feature_names)
    label_hash = hash_labels(labels)
    conn.close()

    pinned = {}
    for name, expected in PINNED_FILES.items():
        actual = sha256(reports / name)
        pinned[name] = {"expected_sha256": expected, "actual_sha256": actual,
                        "match": actual == expected}
    journals = {}
    for name in ("wave2_research_journal.jsonl", "wave3_research_journal.jsonl"):
        ok, reason = ResearchJournal(str(reports / name)).verify_chain()
        journals[name] = {"chain_intact": ok, "reason": reason,
                          "sha256": pinned[name]["actual_sha256"]}
    w4 = json.loads((reports / "wave4_w3_control_reevaluation.json")
                    .read_text(encoding="utf-8"))
    counts_match = counts == {"total": 49989, "admissible": 47852,
                              "data_blocked_action_window": 163, "no_label": 1974}
    result = {
        "check": "wave5_frozen_w1_w4_control_reevaluation",
        "evidence_time": args.evidence_time,
        "warehouse": {
            "path": str(db_path), "open_mode": "mode=ro + query_only=ON",
            "bytes": db_path.stat().st_size, "sha256": sha256(db_path),
        },
        "w3_control": {
            "feature_hash_recomputed": feature_hash,
            "feature_hash_frozen": contracts["feature_hash"],
            "feature_hash_match": feature_hash == contracts["feature_hash"],
            "label_hash_recomputed": label_hash,
            "label_hash_frozen": contracts["label_hash"],
            "label_hash_match": label_hash == contracts["label_hash"],
            "label_counts": counts,
            "label_counts_match_frozen": counts_match,
        },
        "w4_arm_a": {
            "prior_verdict": w4["verdict"],
            "prior_feature_hash": w4["feature_hash_recomputed"],
            "prior_label_hash": w4["label_hash_recomputed"],
            "byte_identity_sha256": pinned["wave4_w3_control_reevaluation.json"]["actual_sha256"],
            "jev_state": "OFF; no events_ai import on numerical path",
            "comparator_state": "UNCHANGED",
        },
        "journals": journals,
        "pinned_artifacts": pinned,
        "provider_calls": {"jev": 0, "mercury": 0, "network": 0},
        "provider_state": {
            "jev": "DISABLED_NOT_CALLED",
            "typesafe_direct": "NOT_TESTED",
            "jev_latest_identity": "ALIAS_UNCERTIFIED_UNCHANGED_FROM_W4",
            "mercury": "DEFAULT_DISABLED_NOT_CALLED",
        },
        "economic_claim": "NONE",
    }
    result["verdict"] = "UNCHANGED" if (
        result["w3_control"]["feature_hash_match"]
        and result["w3_control"]["label_hash_match"]
        and counts_match
        and all(item["match"] for item in pinned.values())
        and all(item["chain_intact"] for item in journals.values())
    ) else "DRIFT"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--reports", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-time", required=True)
    args = parser.parse_args()
    result = verify(args)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"refusing to overwrite differing evidence artifact: {output}")
    output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "verdict": result["verdict"],
                      "feature_hash": result["w3_control"]["feature_hash_recomputed"],
                      "label_hash": result["w3_control"]["label_hash_recomputed"],
                      "counts": result["w3_control"]["label_counts"]}, indent=2))


if __name__ == "__main__":
    main()
