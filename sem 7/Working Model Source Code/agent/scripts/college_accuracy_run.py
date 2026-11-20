"""Seal and run the post-W6 college directional-accuracy evaluation."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3.college_accuracy.contracts import (
    EVIDENCE_TIER, verify_sealed_spec, write_sealed_spec)
from quantplus_intelligence.research_v3.college_accuracy.reporting import (
    sha256, write_manifest, write_reports)
from quantplus_intelligence.research_v3.college_accuracy.runner import run_evaluation
from quantplus_intelligence.research_v3.quantlab.models import (
    HGB_CONFIG, LOGISTIC_CONFIG, RIDGE_CONFIG)

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
REPORTS = ROOT / "reports" / "alpha_v3_1"
DB = BACKEND / "data" / "research_v3" / "warehouse.sqlite3"


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path,
                                   text=True).strip()


def evaluation_spec(created_at: str) -> dict:
    return {
        "spec_version": "college-direction-open-open-v1",
        "created_at_utc": created_at,
        "evidence_tier": EVIDENCE_TIER,
        "authority": "RESEARCH_ONLY_NO_ORDER_AUTHORITY",
        "historical_data_disclosure": (
            "W1-W6 reports, W2 revealed holdout outcomes, and W3 validation metrics were "
            "available before this specification. Therefore no result is a fresh sealed test."),
        "academic_question": (
            "Measure reproducible absolute UP/DOWN classification accuracy and compare it with "
            "training-only majority, fixed-UP, trend and reversal baselines."),
        "targets": {
            "primary": {"horizon_sessions": 20,
                        "return": "future absolute raw-price executable OPEN-to-OPEN return",
                        "up": "strictly > 0", "down": "strictly < 0",
                        "tie": "exactly 0; counted and excluded from binary denominator"},
            "secondary": {"horizon_sessions": 5, "same_mechanics": True},
            "reported_horizons": [5, 20],
            "h60": "OMITTED_INSUFFICIENT_INDEPENDENT_SAMPLE: W3 had 24 monthly dates and about 2 non-overlapping periods",
            "benchmark_relative": "SEPARATE_AND_NOT_USED_AS_UP_DOWN",
        },
        "execution_indexing": {
            "decision": "last completed weekly session; cutoff next local calendar day T00:15 IST",
            "entry": "first eligible observed session OPEN strictly after decision cutoff",
            "exit": "OPEN on the h-th observed NSE session after entry; labelled extension on missing instrument bar",
            "same_close_fill_forbidden": True,
            "exit_ref": "OPEN",
        },
        "windows": {
            "train_start": "2015-06-01", "training_initial_end": "2021-12-31",
            "validation_start": "2022-01-01", "validation_end": "2023-12-31",
            "decision_cadence": "last observed session of each ISO week",
        },
        "folds": {"kind": "four expanding walk-forward folds using existing W3 validation tiles",
                  "n_folds": 4, "embargo_sessions": 20,
                  "purge": "drop training row unless label exit is at least 20 observed sessions before validation start",
                  "random_row_split": False},
        "models": {
            "majority_train": {"rule": "majority class from each fold's purged training rows only"},
            "fixed_up": {"rule": "always UP"},
            "trend_ret60": {"rule": "UP iff PIT ret_60 > 0"},
            "reversal_ret5": {"rule": "UP iff -PIT ret_5 > 0"},
            "ridge": RIDGE_CONFIG,
            "logistic": LOGISTIC_CONFIG,
            "hgb": HGB_CONFIG,
        },
        "decision_rules": {
            "ridge_threshold": 0.0,
            "probability_threshold": 0.5,
            "threshold_comparison": "strict greater-than; equality predicts DOWN",
            "primary_confidence_abstention": "none beyond data/model missingness",
            "probability_confidence_grid": [0.50, 0.55, 0.60, 0.65],
            "grid_use": "development display only; all points retained; no best point selected",
        },
        "samples": {
            "primary_reporting": "COMMON_MODEL_SAMPLE intersection across all seven candidates",
            "coverage_reporting": "ALL_ELIGIBLE labels with missing predictions counted as abstentions",
            "unconditional_accuracy": "correct predictions divided by every eligible non-tie label; abstentions are not correct",
            "answered_accuracy": "correct divided by answered eligible non-tie predictions",
        },
        "uncertainty": {
            "method": "moving decision-session block bootstrap",
            "bootstrap_iterations": 2000, "seed": 20261114,
            "block_sessions_by_horizon": {"5": 1, "20": 4},
            "stocks_within_date_resampled_independently": False,
        },
        "breakdowns": {"year": True, "fold": True,
                       "sector": "UNAVAILABLE_NO_VERIFIED_ASOF_SECTOR_MAP",
                       "regime": "NOT_PREREGISTERED_FOR_THIS_SPRINT"},
        "holdout_policy": {
            "revealed_w2_holdout": ["2024-06-21", "2026-09-17"],
            "reuse_allowed": False,
            "fresh_sealed_holdout": "NEW_SEALED_HOLDOUT_UNAVAILABLE",
        },
        "candidate_selection": (
            "No candidate is selected. All fixed W3 families and all predeclared baselines are "
            "reported. Logistic h20 is designated before scoring only as the primary fitted row "
            "for discussion/figure layout."),
        "data_limits": [
            "raw unadjusted prices; not total return",
            "action-shaped discontinuity windows excluded but action history incomplete",
            "2024-H1 official archive gap outside evaluated window",
            "historical membership includes weak snapshot-floor spells",
            "no verified as-of sector map",
            "fees unavailable for 2022-2023; accuracy is not economics",
        ],
        "inputs": {
            "development_head": git_head(ROOT),
            "service_head": git_head(Path("D:/QP/agent-service")),
            "warehouse_path": str(DB), "warehouse_sha256": sha256(DB),
            "w3_feature_contract_sha256": sha256(REPORTS / "wave3_feature_label_contracts.json"),
            "w3_model_comparison_sha256": sha256(REPORTS / "wave3_model_comparison.json"),
            "w3_research_journal_sha256": sha256(REPORTS / "wave3_research_journal.jsonl"),
            "w6_protocol_sha256": sha256(REPORTS / "wave6_protocol_and_candidate_freeze.json"),
            "w6_real_ledger_sha256": sha256(REPORTS / "wave6_signal_and_paper_ledger.jsonl"),
            "frozen_w3_feature_hash": "634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52",
            "frozen_w3_label_hash": "0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e",
        },
        "forbidden_claims": [
            "fresh holdout", "independent external validation", "forward accuracy",
            "profitable strategy", "investment return", "trading eligibility", "Jev benefit",
        ],
    }


def seal(args) -> None:
    created = args.created_at or datetime.now(timezone.utc).isoformat()
    spec = write_sealed_spec(args.output, evaluation_spec(created))
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "spec_payload_sha256": spec["spec_payload_sha256"],
                      "created_at_utc": spec["created_at_utc"]}, indent=2))


def run(args) -> None:
    spec_path = Path(args.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    ok, reason = verify_sealed_spec(spec)
    if not ok:
        raise RuntimeError(reason)
    result = run_evaluation(spec, args.db or DB)
    test_evidence = (json.loads(Path(args.test_evidence).read_text(encoding="utf-8"))
                     if args.test_evidence else None)
    output = Path(args.output).resolve()
    if spec_path != output / "evaluation_spec.json":
        output.mkdir(parents=True, exist_ok=True)
        target = output / "evaluation_spec.json"
        if target.exists() and target.read_bytes() != spec_path.read_bytes():
            raise RuntimeError("output evaluation_spec.json differs from sealed input")
        target.write_bytes(spec_path.read_bytes())
    report_status = write_reports(result, spec, output, test_evidence=test_evidence)
    input_hashes = dict(spec["inputs"])
    input_hashes["open_to_open_label_hash"] = result["dataset"]["open_to_open_label_hash"]
    input_hashes["snapshot_hash"] = result["dataset"]["snapshot_hash"]
    manifest = write_manifest(
        output, source_root=BACKEND, input_hashes=input_hashes,
        result=result, test_evidence=test_evidence)
    print(json.dumps({"result_id": result["result_id"],
                      "spec_hash": result["spec_hash"],
                      "oof_rows": report_status["oof_rows"],
                      "exceeds_50_rows": report_status["exceeds_50_rows"],
                      "manifest_payload_sha256": manifest["manifest_payload_sha256"]}, indent=2))


def refresh_reports(args) -> None:
    """Regenerate prose/figure/manifest from persisted OOF rows without rescoring."""
    output = Path(args.output).resolve()
    spec = json.loads((output / "evaluation_spec.json").read_text(encoding="utf-8"))
    ok, reason = verify_sealed_spec(spec)
    if not ok:
        raise RuntimeError(reason)
    result = json.loads((output / "directional_accuracy_results.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in
            (output / "oof_predictions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    # Older same-run report writers may not have emitted these two audit fields;
    # derive them once from the majority baseline's unique validation attempts.
    attempts = [row for row in rows if row["model"] == "majority_train"]
    result["dataset"].setdefault("exit_extended", {
        f"h{horizon}": sum(row.get("exit_extended", False) for row in attempts
                            if row["horizon_sessions"] == horizon)
        for horizon in spec["targets"]["reported_horizons"]})
    result["dataset"].setdefault("membership_provenance", {
        f"h{horizon}": {
            "strict": sum(row.get("membership_strict", False) for row in attempts
                          if row["horizon_sessions"] == horizon),
            "weak_or_unknown": sum(not row.get("membership_strict", False) for row in attempts
                                   if row["horizon_sessions"] == horizon),
        } for horizon in spec["targets"]["reported_horizons"]})
    result["oof_rows"] = rows
    test_evidence = (json.loads(Path(args.test_evidence).read_text(encoding="utf-8"))
                     if args.test_evidence else None)
    write_reports(result, spec, output, test_evidence=test_evidence)
    input_hashes = dict(spec["inputs"])
    input_hashes["open_to_open_label_hash"] = result["dataset"]["open_to_open_label_hash"]
    input_hashes["snapshot_hash"] = result["dataset"]["snapshot_hash"]
    manifest = write_manifest(
        output, source_root=BACKEND, input_hashes=input_hashes,
        result=result, test_evidence=test_evidence)
    print(json.dumps({"refreshed": str(output), "result_id": result["result_id"],
                      "manifest_payload_sha256": manifest["manifest_payload_sha256"]}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seal_parser = sub.add_parser("seal-spec")
    seal_parser.add_argument("--output", required=True)
    seal_parser.add_argument("--created-at")
    seal_parser.set_defaults(func=seal)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--spec", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--db")
    run_parser.add_argument("--test-evidence")
    run_parser.set_defaults(func=run)
    refresh_parser = sub.add_parser("refresh-reports")
    refresh_parser.add_argument("--output", required=True)
    refresh_parser.add_argument("--test-evidence")
    refresh_parser.set_defaults(func=refresh_reports)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
