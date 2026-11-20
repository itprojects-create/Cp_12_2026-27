"""Freeze enforcement: effective-config hashing, drift detection, forking (§§55–58).

Git hashes lie about semantics (a comment bump looks like a change; a threshold
edit hidden in a refactor looks like nothing). This module hashes the EFFECTIVE
configuration: function sources for strategy/veto/features, every threshold and
cap value, universe policy, cost model, blackout family bytes, gate bars,
benchmark id. Any semantic drift -> FORWARD_CONFIG_DRIFT, and forward runs
under drift are quarantined from the original experiment (fail-closed §61).

Forking (§57): genuine changes get a new fingerprint + experiment id + forward
start. Old forward history stays attached to the old strategy, untouched.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone

FREEZE_VERSION = "LIVE_FORWARD_FREEZE_V1"


def _fn_hash(fn) -> str:
    return hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()[:16]


def effective_config() -> dict:
    """Hash the effective (semantic) configuration. Deterministic."""
    from app.core import overlay as OV
    from app.core import trend_core as TC
    from app.core import trend_core_v3 as V3
    from app.core import trend_core_v4 as V4
    from app.agents import trader_risk as TR
    from app.data import pit_membership as PM
    from app.events import blackout as BO
    from app.eval import gates as G
    from app.evo import evidence_gates as EG
    from app.evo import promotion as PROM
    cfg = {
        "strategy_fn": _fn_hash(V4.run_core_v4),
        "veto_fn": _fn_hash(OV.veto_fraction),
        "features_fn": _fn_hash(TC.name_features),
        "thresholds": {
            "TOP_K": V4.TOP_K, "TURNOVER_MIN_DELTA": V3.TURNOVER_MIN_DELTA,
            "MIN_HOLD_DAYS": V3.MIN_HOLD_DAYS, "BLACKOUT_DAYS": V3.BLACKOUT_DAYS,
            "PORT_VOL_TARGET": V3.PORT_VOL_TARGET,
            "ELEVATED_GROSS_CAP": V3.ELEVATED_GROSS_CAP,
            "TIER_CAPS": dict(sorted(V3.TIER_CAPS.items())), "SECTOR_CAP": V3.SECTOR_CAP,
            "GROSS_CAP": TC.GROSS_CAP, "COST_PER_SIDE": TC.COST_PER_SIDE,
            "MAX_POSITION_PCT": TC.MAX_POSITION_PCT,
            "FIXED_BASE_SIZE": TR.FIXED_BASE_SIZE},
        "universe_policy": {"mode": "pit-nonstrict-weekly",
                            "membership_source_version": PM.PU.source_version()},
        "cost_model": {"version": "env-v1", "roundtrip": TC.COST_PER_SIDE * 2},
        "blackout_family": {"version": BO.BLACKOUT_FAMILY_VERSION,
                            "rules": [r.frozen_dict() for r in BO.BLACKOUT_FAMILY_V1]},
        "gates": {"direction": {"accuracy_min": G.ACCURACY_MIN,
                                "min_decisive": G.MIN_DECISIVE,
                                "no_edge_hold_min": G.NO_EDGE_HOLD_MIN,
                                "trade_lo": G.TRADE_RATE_LO,
                                "trade_hi": G.TRADE_RATE_HI},
                  "promotion": PROM.VERSION, "risk": EG.RISK_VERSION,
                  "execution": EG.EXEC_VERSION, "quality": EG.QUALITY_VERSION},
        "benchmark": "NIFTY50_TRI+v4-eqw",
    }
    cfg["config_hash"] = hashlib.sha256(
        json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return cfg


def freeze(path: str | None = None) -> dict:
    """Write the freeze artifact (§55). Returns {path, freeze}."""
    import os
    doc = {"freeze_version": FREEZE_VERSION,
           "frozen_at": datetime.now(timezone.utc).isoformat(),
           "effective_config": effective_config()}
    path = path or os.path.join(
        "data", f"strategy_freeze_{datetime.now(timezone.utc).date().isoformat()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    return {"path": path, "freeze": doc}


def verify(path: str) -> dict:
    """Compare live effective config against a freeze artifact."""
    frozen = json.load(open(path, encoding="utf-8"))
    live = effective_config()
    want = frozen["effective_config"]
    diffs = []
    if live["config_hash"] != want.get("config_hash"):
        for section in ("thresholds", "blackout_family", "gates", "universe_policy",
                        "cost_model", "benchmark"):
            if json.dumps(live.get(section), sort_keys=True, default=str) != json.dumps(
                    want.get(section), sort_keys=True, default=str):
                diffs.append(section)
        for fn in ("strategy_fn", "veto_fn", "features_fn"):
            if live.get(fn) != want.get(fn):
                diffs.append(fn)
    return {"freeze": frozen.get("freeze_version", "?"),
            "drift": bool(diffs), "drift_sections": diffs,
            "verdict": "FORWARD_CONFIG_DRIFT" if diffs else "MATCH",
            "live_hash": live["config_hash"],
            "frozen_hash": want.get("config_hash")}


def fork_experiment(old_experiment_id: str, reason: str,
                    manifest_dir: str = "data/experiments") -> dict:
    """§57: genuine strategy changes fork — new fingerprint, new id, new forward
    start. Old history untouched (nothing here mutates prior artifacts)."""
    import os
    live = effective_config()
    new_id = f"{old_experiment_id}-fork-{live['config_hash'][:8]}"
    now = datetime.now(timezone.utc).isoformat()
    manifest = {"experiment_id": new_id, "forked_from": old_experiment_id,
                "fork_reason": reason, "forward_start": now,
                "strategy_fingerprint": f"strat-{live['config_hash']}",
                "effective_config": live}
    os.makedirs(os.path.join(manifest_dir, new_id), exist_ok=True)
    path = os.path.join(manifest_dir, new_id, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return {"experiment_id": new_id, "forward_start": now, "manifest": path}
