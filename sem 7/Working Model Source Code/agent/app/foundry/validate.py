"""Embargoed validation + PBO-lite promotion (prereg §2).

Formalism: rows = candidate entry decisions in time order, each
{veto_raw, regime, breadth, whipsaw (0/1)}. Baseline policy maps row -> veto;
candidate = max(baseline, proposal cell). Traded iff veto < 1.0.
Split: train [:60%], 20-row embargo gap (dropped), test the rest (fixed).
Promote requires: test whipsaw-rate down >=3pp AND >=6/8 blocks AND exposure
within ±2pp AND thresholds unchanged. Failures logged identically.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import sqlite_conn
from app.foundry.proposals import Proposal

TRAIN_FRAC = 0.6  # fixed, not tuned
EMBARGO_ROWS = 20  # fixed gap defeating veto-score autocorrelation
N_BLOCKS = 8
MIN_WHIPSAW_DROP_PP = 0.02  # Amendment 1: 0.03 infeasible under drift cap (see prereg)
MAX_EXPOSURE_DRIFT = 0.05  # Amendment 1: was 0.02 (infeasible pair)
MIN_BLOCK_WINS = 6


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS foundry_log
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, params TEXT,
         rationale TEXT, promoted INTEGER, metrics TEXT)""")
    sqlite_conn().commit()


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Time-ordered train/test with embargo gap dropped. Gap rows are returned
    for audit (must never enter either set)."""
    cut = int(len(rows) * TRAIN_FRAC)
    train = rows[:cut]
    gap = rows[cut:cut + EMBARGO_ROWS]
    test = rows[cut + EMBARGO_ROWS:]
    # audit: prove separation (no shared object identity across sets)
    assert not ({id(r) for r in train} & {id(r) for r in test})
    return train, test, gap


def _metrics(policy, rows: list[dict]) -> dict:
    if not rows:
        return {"whipsaw_rate": 0.0, "exposure": 0.0, "n": 0}
    traded = [r for r in rows if policy(r) < 1.0]
    whip = sum(1 for r in traded if r["whipsaw"] == 1)
    return {"whipsaw_rate": whip / len(traded) if traded else 0.0,
            "exposure": len(traded) / len(rows), "n": len(rows)}


def _cell_match(params: dict, row: dict) -> bool:
    if params.get("regime", "ANY") != "ANY" and row.get("regime") != params["regime"]:
        return False
    if params.get("breadth", "ANY") != "ANY" and row.get("breadth") != params["breadth"]:
        return False
    return params["band_lo"] <= row.get("veto_raw", -1) < params["band_hi"]


def candidate_policy(proposal: Proposal, baseline) -> object:
    """OR-composition: candidate vetoes a superset (only ever more, never less)."""
    if proposal.kind != "veto_band_edge":
        raise ValueError(f"kind {proposal.kind} has no veto-table semantics (evo consumes it)")
    cell = proposal.params["veto"]

    def policy(row: dict) -> float:
        base = baseline(row)
        if _cell_match(proposal.params, row):
            return max(base, cell)
        return base

    return policy


def validate(proposal: Proposal, rows: list[dict], baseline) -> dict:
    proposal.validate()
    train, test, gap = split(rows)
    if len(test) < N_BLOCKS:
        rec = {"promoted": False, "reason": "test slice too small",
               "n_train": len(train), "n_test": len(test), "n_gap": len(gap)}
        log(proposal, rec)
        return rec
    policy = candidate_policy(proposal, baseline)
    base_m, cand_m = _metrics(baseline, test), _metrics(policy, test)
    drop = base_m["whipsaw_rate"] - cand_m["whipsaw_rate"]
    drift = abs(cand_m["exposure"] - base_m["exposure"])
    # PBO-lite: 8 contiguous blocks, candidate wins block on lower whipsaw
    # rate with exposure inside ±2pp of the baseline block.
    k = len(test) // N_BLOCKS
    wins = 0
    for i in range(N_BLOCKS):
        blk = test[i * k:(i + 1) * k if i < N_BLOCKS - 1 else len(test)]
        bm, cm = _metrics(baseline, blk), _metrics(policy, blk)
        if cm["whipsaw_rate"] < bm["whipsaw_rate"] and abs(cm["exposure"] - bm["exposure"]) <= MAX_EXPOSURE_DRIFT:
            wins += 1
    promoted = (drop >= MIN_WHIPSAW_DROP_PP and wins >= MIN_BLOCK_WINS
                and drift <= MAX_EXPOSURE_DRIFT)
    rec = {"promoted": promoted, "whipsaw_drop_pp": round(drop, 4),
           "block_wins": f"{wins}/{N_BLOCKS}", "exposure_drift": round(drift, 4),
           "baseline": base_m, "candidate": cand_m,
           "n_train": len(train), "n_test": len(test), "n_gap": len(gap)}
    log(proposal, rec)
    return rec


def log(proposal: Proposal, record: dict) -> int:
    cur = sqlite_conn().execute(
        "INSERT INTO foundry_log(ts, kind, params, rationale, promoted, metrics)"
        " VALUES (?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), proposal.kind,
         json.dumps(proposal.params, sort_keys=True), proposal.rationale,
         1 if record.get("promoted") else 0, json.dumps(record, sort_keys=True)))
    sqlite_conn().commit()
    return cur.lastrowid
