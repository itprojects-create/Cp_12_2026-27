"""Read-only Wave 6 verifier for W0-W5 controls and user/V2 ledgers."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3.lab.journal import ResearchJournal
from quantplus_intelligence.research_v3.monitor.journal import LivingResearchJournal

W3_FEATURE = "634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52"
W3_LABEL = "0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e"
PINNED_REPORTS = {
    "wave2_research_journal.jsonl": "c24c9b0491fa9bbd819b12393ce84a1aa5321f40c35e48d0b3c233986f50c2e7",
    "wave3_research_journal.jsonl": "ab9a77695e87b49960c9086815b3de07a642f9cb15e82e1ba953246aa0f37426",
    "wave3_feature_label_contracts.json": "d637413444e9afe09a705191f05d5e3610fac0d82684c51831a5c42538c9de77",
    "wave4_ablation_results.json": "c86804fd48c030cf3092fbb1e68bcb0062acbcb476dfa1690fb580f93d8c3c8d",
    "wave4_w3_control_reevaluation.json": "e3f1d782fe2fd4a6cc8e0518d9e63be04a186ef4e72bbeba116b144dc177baeb",
    "wave5_event_capture_manifest.json": "b13255d0f8a406c1f64130c210ba46c5713bf4ce9a9aea2374da42024cb90a1b",
    "wave5_research_monitor_log.jsonl": "14390bb9390ed7f64436b64f07365a124aacdf94ce95cc632defc431e5ce869f",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(args) -> dict:
    reports = Path(args.reports).resolve()
    dev = Path(args.dev_root).resolve()
    prod = Path(args.prod_root).resolve()
    baseline = json.loads(Path(args.baseline_hashes).read_text(encoding="utf-8"))
    w5 = json.loads(Path(args.w5_control_json).read_text(encoding="utf-8"))
    pinned = {}
    for name, expected in PINNED_REPORTS.items():
        actual = sha256(reports / name)
        pinned[name] = {"expected_sha256": expected, "actual_sha256": actual,
                        "match": actual == expected}
    journals = {}
    for name in ("wave2_research_journal.jsonl", "wave3_research_journal.jsonl"):
        ok, reason = ResearchJournal(reports / name).verify_chain()
        journals[name] = {"chain_intact": ok, "reason": reason}
    w5_journal = LivingResearchJournal(reports / "wave5_research_monitor_log.jsonl")
    ok, reason = w5_journal.verify_chain()
    journals["wave5_research_monitor_log.jsonl"] = {
        "chain_intact": ok, "reason": reason,
        "head_hash": w5_journal.status()["head_hash"],
    }
    event_capture = json.loads(
        (reports / "wave5_event_capture_manifest.json").read_text(encoding="utf-8"))

    controlled_paths = {
        "dev_local_workspace": dev / ".local-data" / "workspace.json",
        "w0_forecast_backup": reports / "backups" / "forecast_ledger_w0_backup.sqlite3",
        "prod_forecast_ledger": prod / "data" / "forecast_ledger.sqlite3",
        "prod_v2_paper_pnl": prod / "data" / "forecast_reports" / "paper_pnl.jsonl",
        "prod_paper_signals": prod / "data" / "paper_signals.jsonl",
        "warehouse": dev / "backend-extension" / "data" / "research_v3" / "warehouse.sqlite3",
    }
    controlled = {}
    for key, path in controlled_paths.items():
        actual = sha256(path) if path.is_file() else None
        expected = baseline["files"].get(key)
        controlled[key] = {"path": str(path), "expected_pre_w6_sha256": expected,
                           "actual_sha256": actual, "match": actual == expected}

    contracts = json.loads(
        (reports / "wave3_feature_label_contracts.json").read_text(encoding="utf-8"))
    counts = w5["w3_control"]["label_counts"]
    expected_counts = {"total": 49989, "admissible": 47852,
                       "data_blocked_action_window": 163, "no_label": 1974}
    w3 = {
        "feature_hash": contracts["feature_hash"],
        "feature_hash_recomputed": w5["w3_control"]["feature_hash_recomputed"],
        "feature_match": contracts["feature_hash"] == W3_FEATURE ==
                         w5["w3_control"]["feature_hash_recomputed"],
        "label_hash": contracts["label_hash"],
        "label_hash_recomputed": w5["w3_control"]["label_hash_recomputed"],
        "label_match": contracts["label_hash"] == W3_LABEL ==
                       w5["w3_control"]["label_hash_recomputed"],
        "label_counts": counts,
        "counts_match": counts == expected_counts,
    }
    arm_a = json.loads(
        (reports / "wave4_ablation_results.json").read_text(encoding="utf-8"))["arms"]["A"]
    result = {
        "artifact_version": "wave6_w0_w5_frozen_controls/1",
        "evidence_time": args.evidence_time,
        "w3_control": w3,
        "w4_arm_a": {"status": arm_a["status"],
                      "byte_identity_sha256": pinned[
                          "wave4_w3_control_reevaluation.json"]["actual_sha256"]},
        "w2_w3_w5_journals": journals,
        "pinned_reports": pinned,
        "controlled_files_pre_post": controlled,
        "w5_event_capture": {
            "pipeline_status": event_capture["pipeline_status"],
            "enabled": event_capture["config_contract"]["enabled"],
            "schedule_enabled": event_capture["schedule_enabled"],
            "actual_rows": event_capture["actual_legally_captured_rows_by_w5"],
        },
        "authority": {
            "jev_money_authority": 0,
            "mercury_money_authority": 0,
            "live_broker_order_authority": 0,
            "event_ai_state": "OFF",
        },
        "provider_calls": {"jev": 0, "mercury": 0, "other_model": 0},
    }
    result["verdict"] = "UNCHANGED" if (
        w5.get("verdict") == "UNCHANGED"
        and w3["feature_match"] and w3["label_match"] and w3["counts_match"]
        and arm_a["status"] == "UNCHANGED"
        and all(row["match"] for row in pinned.values())
        and all(row["chain_intact"] for row in journals.values())
        and all(row["match"] for row in controlled.values())
        and event_capture["pipeline_status"] == "NOT_CONFIGURED"
        and event_capture["actual_legally_captured_rows_by_w5"] == 0
    ) else "DRIFT"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", required=True)
    parser.add_argument("--dev-root", required=True)
    parser.add_argument("--prod-root", required=True)
    parser.add_argument("--baseline-hashes", required=True)
    parser.add_argument("--w5-control-json", required=True)
    parser.add_argument("--evidence-time", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = verify(args)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"refusing to overwrite differing evidence artifact: {output}")
    output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "verdict": result["verdict"]}, indent=2))
    if result["verdict"] != "UNCHANGED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
