"""Verify Wave 5 hashes, two-repository sync and no-stage/no-secret controls."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path


SECRET_PATTERN = re.compile(
    # Prefixed credential tokens must START at a token boundary and carry a
    # long random body: bare identifiers inside prose (mints_new_revision,
    # ADANIPORTS_NS_1d, costs_same_close) no longer trigger. A Bearer scheme
    # likewise requires a long token body, not ordinary words.
    rb"(?<![A-Za-z0-9_])(?:xpl_|sk-|ts_)[A-Za-z0-9_\-]{32,}"
    rb"|(?<![A-Za-z0-9_])Bearer\s+[A-Za-z0-9_\-.]{32,}", re.I)
FORBIDDEN_AUTHORITY_NAMES = {
    "place_order", "submit_order", "cancel_order", "route_order", "paper_engine",
    "mutate_balance", "live_order", "broker_order", "risk_policy",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def staged_count(repo: Path) -> int:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-uno"], cwd=repo,
        capture_output=True, text=True, check=True)
    return sum(line and line[0] != " " for line in result.stdout.splitlines())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dev-root", required=True)
    parser.add_argument("--prod-root", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve()
    dev_root = Path(args.dev_root).resolve()
    prod_root = Path(args.prod_root).resolve()
    dev_backend = dev_root / "backend-extension"
    reports = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    expected_payload_hash = manifest["manifest_payload_sha256"]
    payload = dict(manifest)
    payload.pop("manifest_payload_sha256")
    actual_payload_hash = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()

    code_checks = []
    for relative, expected in manifest["code_and_tests"].items():
        path = dev_backend / relative
        actual = sha256(path) if path.is_file() else None
        code_checks.append({"path": relative, "expected": expected, "actual": actual,
                            "match": actual == expected})
    artifact_checks = []
    for relative, expected in manifest["report_artifacts"].items():
        path = reports / relative
        actual = sha256(path) if path.is_file() else None
        artifact_checks.append({"path": relative, "expected": expected, "actual": actual,
                                "match": actual == expected})
    evolving_checks = []
    for relative, policy in manifest.get("evolving_artifacts", {}).items():
        path = reports / relative
        raw = path.read_bytes() if path.is_file() else b""
        markers = [marker.encode("utf-8") for marker in policy["required_markers"]]
        actual = hashlib.sha256(raw).hexdigest() if raw else None
        evolving_checks.append({
            "path": relative,
            "wave5_snapshot_sha256": policy["wave5_snapshot_sha256"],
            "actual_sha256": actual,
            "snapshot_byte_match": actual == policy["wave5_snapshot_sha256"],
            "required_markers_present": bool(raw) and all(marker in raw for marker in markers),
            "match": bool(raw) and all(marker in raw for marker in markers),
            "policy": "post-W5 acceptance matrix may add later-wave rows; W5 markers immutable",
        })
    sync_checks = []
    for row in manifest["two_repo_sync"]:
        relative = row["relative_path"]
        dev_path = dev_backend / relative
        prod_path = prod_root / relative
        dev_hash = sha256(dev_path) if dev_path.is_file() else None
        prod_hash = sha256(prod_path) if prod_path.is_file() else None
        sync_checks.append({
            "path": relative,
            "development_sha256": dev_hash,
            "production_sha256": prod_hash,
            "match": dev_hash is not None and dev_hash == prod_hash
                     and dev_hash == row["development_sha256"],
        })

    scan_paths = [dev_backend / relative for relative in manifest["code_and_tests"]]
    scan_paths += [reports / relative for relative in manifest["report_artifacts"]]
    scan_paths += [reports / relative for relative in manifest.get("evolving_artifacts", {})]
    secret_hits = [str(path) for path in scan_paths
                   if path.is_file() and SECRET_PATTERN.search(path.read_bytes())]
    authority_hits = []
    for relative in manifest["code_and_tests"]:
        path = dev_backend / relative
        if path.suffix != ".py" or not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app"):
                        authority_hits.append(f"{relative}:runtime-import:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module \
                    and node.module.startswith("app"):
                authority_hits.append(f"{relative}:runtime-import:{node.module}")
        for name in sorted(names & FORBIDDEN_AUTHORITY_NAMES):
            authority_hits.append(f"{relative}:forbidden-name:{name}")

    summary = {
        "manifest": str(manifest_path),
        "manifest_payload_hash_match": actual_payload_hash == expected_payload_hash,
        "code_checks": code_checks,
        "artifact_checks": artifact_checks,
        "evolving_artifact_checks": evolving_checks,
        "sync_checks": sync_checks,
        "secret_hits": secret_hits,
        "authority_hits": authority_hits,
        "staged_counts": {
            "development": staged_count(dev_root),
            "production": staged_count(prod_root),
        },
    }
    summary["ok"] = (
        summary["manifest_payload_hash_match"]
        and all(row["match"] for row in code_checks)
        and all(row["match"] for row in artifact_checks)
        and all(row["match"] for row in evolving_checks)
        and all(row["match"] for row in sync_checks)
        and not secret_hits
        and not authority_hits
        and not any(summary["staged_counts"].values())
    )
    print(json.dumps(summary, indent=2))
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
