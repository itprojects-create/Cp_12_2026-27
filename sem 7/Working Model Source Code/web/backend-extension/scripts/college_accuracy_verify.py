"""Verify college accuracy artifacts, source inputs and sealed spec."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3.college_accuracy.contracts import (
    canonical_json, verify_sealed_spec)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(manifest_path: Path, backend: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = dict(manifest)
    expected_payload = payload.pop("manifest_payload_sha256")
    actual_payload = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    output = manifest_path.parent
    root = backend.parent
    artifacts = []
    for relative, expected in manifest["artifacts"].items():
        path = output / relative
        actual = sha256(path) if path.is_file() else None
        artifacts.append({"path": relative, "expected": expected,
                          "actual": actual, "match": actual == expected})
    code = []
    for relative, expected in manifest["code_and_tests"].items():
        path = backend / relative
        actual = sha256(path) if path.is_file() else None
        code.append({"path": relative, "expected": expected,
                     "actual": actual, "match": actual == expected})
    spec = json.loads((output / "evaluation_spec.json").read_text(encoding="utf-8"))
    spec_ok, spec_reason = verify_sealed_spec(spec)
    input_checks = []
    input_paths = {
        "warehouse_sha256": backend / "data/research_v3/warehouse.sqlite3",
        "w3_feature_contract_sha256": root / "reports/alpha_v3_1/wave3_feature_label_contracts.json",
        "w3_model_comparison_sha256": root / "reports/alpha_v3_1/wave3_model_comparison.json",
        "w3_research_journal_sha256": root / "reports/alpha_v3_1/wave3_research_journal.jsonl",
        "w6_protocol_sha256": root / "reports/alpha_v3_1/wave6_protocol_and_candidate_freeze.json",
        "w6_real_ledger_sha256": root / "reports/alpha_v3_1/wave6_signal_and_paper_ledger.jsonl",
    }
    for key, path in input_paths.items():
        expected = manifest["inputs"][key]
        actual = sha256(path) if path.is_file() else None
        input_checks.append({"input": key, "path": str(path), "expected": expected,
                             "actual": actual, "match": actual == expected})
    sync_checks = []
    service_root = Path("D:/QP/agent-service")
    for row in manifest.get("two_repo_sync", []):
        relative = row["relative_path"]
        dev_path, service_path = backend / relative, service_root / relative
        dev_hash = sha256(dev_path) if dev_path.is_file() else None
        service_hash = sha256(service_path) if service_path.is_file() else None
        sync_checks.append({"relative_path": relative,
                            "development_sha256": dev_hash,
                            "service_sha256": service_hash,
                            "match": dev_hash is not None and dev_hash == service_hash
                                     == row["development_sha256"]})
    result = {
        "manifest_payload_hash_match": actual_payload == expected_payload,
        "sealed_spec_valid": spec_ok, "sealed_spec_reason": spec_reason,
        "artifact_checks": artifacts, "code_checks": code,
        "input_checks": input_checks,
        "sync_checks": sync_checks,
        "frozen_w3_hashes_match": (
            manifest["frozen_w3_controls"]["feature_hash"] ==
            "634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52"
            and manifest["frozen_w3_controls"]["label_hash"] ==
            "0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e"),
    }
    result["ok"] = (result["manifest_payload_hash_match"] and spec_ok
                    and result["frozen_w3_hashes_match"]
                    and all(row["match"] for row in artifacts)
                    and all(row["match"] for row in code)
                    and all(row["match"] for row in input_checks)
                    and all(row["match"] for row in sync_checks))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--backend", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    result = verify(Path(args.manifest).resolve(), Path(args.backend).resolve())
    print(json.dumps(result, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
