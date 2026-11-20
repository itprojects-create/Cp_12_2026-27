"""Freeze enforcement tests (§83). Hermetic (monkeypatched constants)."""
from __future__ import annotations

from app.governance import freeze as FRZ


def test_effective_config_stable_and_hashed():
    a = FRZ.effective_config()
    b = FRZ.effective_config()
    assert a == b and len(a["config_hash"]) == 16
    assert set(a["thresholds"]) >= {"TOP_K", "GROSS_CAP", "COST_PER_SIDE"}
    assert a["blackout_family"]["version"] == "BLACKOUT_FAMILY_V1"


def _frozen_file(tmp_path):
    import json
    cfg = FRZ.effective_config()  # capture BEFORE any tampering
    path = str(tmp_path / "freeze.json")
    json.dump({"freeze_version": FRZ.FREEZE_VERSION, "effective_config": cfg},
              open(path, "w", encoding="utf-8"))
    return path


def test_strategy_code_drift_detected(tmp_path, monkeypatch):
    import app.core.trend_core_v4 as V4
    path = _frozen_file(tmp_path)
    base = FRZ.effective_config()["config_hash"]
    monkeypatch.setattr(V4, "TOP_K", 999)
    assert FRZ.effective_config()["config_hash"] != base
    rec = FRZ.verify(path)
    assert rec["verdict"] == "FORWARD_CONFIG_DRIFT"
    assert "thresholds" in rec["drift_sections"]


def test_gate_and_blackout_drift_detected(tmp_path, monkeypatch):
    import app.eval.gates as G
    path = _frozen_file(tmp_path)
    monkeypatch.setattr(G, "ACCURACY_MIN", 0.99)
    rec = FRZ.verify(path)
    assert rec["verdict"] == "FORWARD_CONFIG_DRIFT"
    assert "gates" in rec["drift_sections"]


def test_old_experiment_refuses_new_fingerprint_and_fork_works(tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    from forward_week import run_week
    from datetime import datetime, timezone
    freeze = FRZ.freeze(str(tmp_path / "fr.json"))
    import app.core.trend_core_v4 as V4
    orig = V4.TOP_K
    V4.TOP_K = 999
    try:
        art = run_week(now=datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc),
                       dry_run=False, forward_bars=[],
                       fingerprint_override="CALM|UP|mid",
                       out_path=str(tmp_path / "noj.json"),
                       freeze_path=freeze["path"])
    finally:
        V4.TOP_K = orig
    assert art["verdict"] == "NO_JUDGMENT"  # quarantined, no judging performed
    assert "judged" not in art
    forked = FRZ.fork_experiment("event_blackout_v1", "threshold change trial",
                                 manifest_dir=str(tmp_path))
    assert forked["experiment_id"].startswith("event_blackout_v1-fork-")
    assert forked["forward_start"] >= "2026-10-10"


def test_freeze_script_roundtrip(tmp_path):
    rec = FRZ.freeze(str(tmp_path / "fr2.json"))
    assert FRZ.verify(rec["path"])["verdict"] == "MATCH"
    assert rec["freeze"]["freeze_version"] == "LIVE_FORWARD_FREEZE_V1"
