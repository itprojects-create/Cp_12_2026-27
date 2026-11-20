"""Strict Wave 6 hash/sync/secret/authority verifier."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

SECRET_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9_])(?:xpl_|sk-|ts_)[A-Za-z0-9_\-]{32,}"
    rb"|(?<![A-Za-z0-9_])Bearer\s+[A-Za-z0-9_\-.]{32,}", re.I)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def staged_count(repo: Path) -> int:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-uno"], cwd=repo,
        capture_output=True, text=True, check=True)
    return sum(bool(line) and line[0] != " " for line in result.stdout.splitlines())


def verify(manifest_path: Path, dev_root: Path, prod_root: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = dict(manifest)
    expected_payload = payload.pop("manifest_payload_sha256")
    actual_payload = hashlib.sha256(canonical(payload).encode()).hexdigest()
    dev_backend = dev_root / "backend-extension"
    reports = manifest_path.parent
    code_checks = []
    for relative, expected in manifest["code_and_tests"].items():
        path = dev_backend / relative
        actual = sha256(path) if path.is_file() else None
        code_checks.append({"path": relative, "expected": expected, "actual": actual,
                            "match": actual == expected})
    frontend_checks = []
    for relative, expected in manifest["frontend_authoritative_adapter"].items():
        path = dev_root / relative
        actual = sha256(path) if path.is_file() else None
        frontend_checks.append({"path": relative, "expected": expected, "actual": actual,
                                "match": actual == expected})
    artifact_checks = []
    for relative, expected in manifest["report_artifacts"].items():
        path = reports / relative
        actual = sha256(path) if path.is_file() else None
        artifact_checks.append({"path": relative, "expected": expected, "actual": actual,
                                "match": actual == expected})
    sync_checks = []
    for row in manifest["two_repo_sync"]:
        relative = row["relative_path"]
        dev_path, prod_path = dev_backend / relative, prod_root / relative
        dh = sha256(dev_path) if dev_path.is_file() else None
        ph = sha256(prod_path) if prod_path.is_file() else None
        sync_checks.append({"path": relative, "development_sha256": dh,
                            "production_sha256": ph,
                            "match": dh is not None and dh == ph == row["development_sha256"]})
    scan_paths = ([dev_backend / relative for relative in manifest["code_and_tests"]]
                  + [dev_root / relative for relative in manifest["frontend_authoritative_adapter"]]
                  + [reports / relative for relative in manifest["report_artifacts"]])
    secret_hits = [str(path) for path in scan_paths
                   if path.is_file() and SECRET_PATTERN.search(path.read_bytes())]
    authority_hits = []
    for relative in manifest["code_and_tests"]:
        path = dev_backend / relative
        if path.suffix != ".py" or not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app"):
                        authority_hits.append(f"{relative}:runtime-import:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                authority_hits.append(f"{relative}:runtime-import:{node.module}")
    result = {
        "manifest_payload_hash_match": actual_payload == expected_payload,
        "code_checks": code_checks, "frontend_checks": frontend_checks,
        "artifact_checks": artifact_checks, "sync_checks": sync_checks,
        "secret_hits": secret_hits, "authority_hits": authority_hits,
        "staged_counts": {"development": staged_count(dev_root),
                          "production": staged_count(prod_root)},
    }
    result["ok"] = (
        result["manifest_payload_hash_match"]
        and all(row["match"] for row in code_checks)
        and all(row["match"] for row in frontend_checks)
        and all(row["match"] for row in artifact_checks)
        and all(row["match"] for row in sync_checks)
        and not secret_hits and not authority_hits
        and not any(result["staged_counts"].values()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dev-root", required=True)
    parser.add_argument("--prod-root", required=True)
    args = parser.parse_args()
    result = verify(Path(args.manifest).resolve(), Path(args.dev_root).resolve(),
                    Path(args.prod_root).resolve())
    print(json.dumps(result, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
