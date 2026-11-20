"""Reproduce an experiment as closely as data/versioning allows (§28).

Usage: python scripts/reproduce_experiment.py EXP-00001 [--manifest-dir data/experiments]

Re-resolves: hypothesis fingerprint from the stored body, DSL program
compilation (when the body carries one), dataset registry status, gateset and
config hashes. Exact historical bars are NOT silently substituted: when live
data cannot reconstruct the original window, that is reported explicitly.
Exit 0 prints the verdict; exit 2 means the experiment id is unknown.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def reproduce(exp_id: str, manifest_dir: str = "data/experiments") -> dict:
    from app.db import sqlite_conn
    from app.governance.constitution import dataset_status
    from app.research import fingerprints as FP

    row = sqlite_conn().execute(
        "SELECT id, hypothesis_fp, body, status, ts FROM research_experiments"
        " WHERE id=?", (exp_id,)).fetchone()
    if row is None:
        return {"experiment": exp_id, "found": False}
    body = json.loads(row[2])
    checks: dict = {"experiment_row": True, "status": row[3]}
    hypo = sqlite_conn().execute(
        "SELECT body FROM research_hypotheses WHERE fp=?", (row[1],)).fetchone()
    if hypo:
        recomputed = FP.hypothesis_fingerprint(json.loads(hypo[0]))
        checks["hypothesis_fp_match"] = recomputed == row[1]
    else:
        checks["hypothesis_fp_match"] = "hypothesis row absent"
    dsl = body.get("dsl_program")
    if isinstance(dsl, dict):
        from app.foundry import dsl as DSL
        try:
            compiled = DSL.compile_program(dsl)
            checks["dsl_recompiles"] = True
            checks["dsl_fp_match"] = compiled.fingerprint == body.get("strategy_fp")
        except ValueError as e:
            checks["dsl_recompiles"] = f"REJECTED: {e}"
    else:
        checks["dsl_recompiles"] = "no program stored"
    checks["dataset_status_now"] = str(dataset_status(body.get("dataset", "")))
    mpath = os.path.join(manifest_dir, exp_id, "manifest.json")
    checks["manifest_present"] = os.path.exists(mpath)
    if os.path.exists(mpath):
        man = json.load(open(mpath, encoding="utf-8"))
        checks["manifest_versions"] = {
            k: man.get(k, "") for k in (
                "pit_membership_version", "membership_hash", "taxonomy_version",
                "classifier_version", "blackout_ruleset_version",
                "data_registry_version", "evidence_class", "gate_version")}
        # membership source drift check (informational — vendored file is fixed,
        # so drift means the environment changed, not the experiment)
        if man.get("pit_membership_version"):
            from app.data import pit_universe as PU
            try:
                checks["membership_source_matches_now"] = (
                    PU.source_version() == man["pit_membership_version"])
            except FileNotFoundError:
                checks["membership_source_matches_now"] = "source file absent"
        # event batches referenced by the manifest must exist in the ledger
        from app.db import sqlite_conn as _conn
        try:
            missing = [b for b in (man.get("event_batch_ids") or [])
                       if not _conn().execute(
                           "SELECT 1 FROM event_batches WHERE batch_id=?", (b,)).fetchone()]
        except Exception:
            missing = list(man.get("event_batch_ids") or [])
        checks["event_batches_missing"] = missing
        # §76: required dataset artifacts must exist in the acquisition ledger
        try:
            missing_art = [h for h in (man.get("artifact_hashes") or [])
                           if not _conn().execute(
                               "SELECT 1 FROM acquisition_ledger WHERE artifact_hash LIKE ?",
                               (h + "%",)).fetchone()]
        except Exception:
            missing_art = list(man.get("artifact_hashes") or [])
        checks["artifact_hashes_missing"] = missing_art
        if missing_art:
            checks["artifact_note"] = ("today's files must not silently substitute "
                                       "the pinned artifacts")
        checks["event_batches_missing"] = missing
    checks["bars_reconstructed"] = False
    checks["bars_note"] = ("exact historical bars are never silently substituted; "
                           "re-run the frozen backtest entrypoint for the window if needed")
    if checks.get("event_batches_missing") or checks.get("artifact_hashes_missing"):
        checks["reproducibility"] = ("NOT EXACTLY REPRODUCIBLE: referenced event batches "
                                     "or dataset artifacts absent from this ledger")
    else:
        checks["reproducibility"] = "manifest-complete (bars excluded by design)"
    return {"experiment": exp_id, "found": True, "checks": checks,
            "manifest": mpath if os.path.exists(mpath) else None}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment_id")
    ap.add_argument("--manifest-dir", default="data/experiments")
    a = ap.parse_args()
    rec = reproduce(a.experiment_id, a.manifest_dir)
    print(json.dumps(rec, indent=2))
    if not rec.get("found"):
        sys.exit(2)


if __name__ == "__main__":
    main()
