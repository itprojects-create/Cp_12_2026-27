"""Stable fingerprints for hypotheses, strategies, data, experiments (§7).

Canonical-JSON sha256. Identical logic -> identical fingerprint; any meaningful
modification -> distinct fingerprint. Used for duplicates, lineage, and corpse
matching (research memory refuses rediscovery without new evidence).
"""
from __future__ import annotations

import hashlib
import json


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str)


def fp(obj: object) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()[:16]


def hypothesis_fingerprint(hypothesis: dict) -> str:
    body = {k: hypothesis.get(k) for k in (
        "title", "thesis", "economic_reason", "strategy_family",
        "required_features", "parameter_ranges", "claimed_mechanism")}
    return "hyp-" + fp(body)


def strategy_logic_fingerprint(program: dict) -> str:
    return "strat-" + fp(program.get("ops", program))


def parameter_fingerprint(params: dict) -> str:
    return "par-" + fp(params)


def data_fingerprint(source: str, universe: list[str] | tuple,
                     start: str, end: str, features: list[str] | tuple) -> str:
    return "data-" + fp({"source": source, "universe": sorted(universe),
                         "start": start, "end": end,
                         "features": sorted(features)})


def experiment_fingerprint(strategy_fp: str, data_fp: str, config: dict,
                           gateset: str) -> str:
    return "exp-" + fp({"strategy": strategy_fp, "data": data_fp,
                        "config": config, "gateset": gateset})
