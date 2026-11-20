"""Arena: allocation, judging rounds, death, resurrection (prereg §§3-6).

Operates on forward-paper decision streams supplied by the caller (Day-6 clock).
No market data fetching here, no LLM anywhere. All transitions logged.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from app.db import sqlite_conn
from app.evo import store
from app.evo.genome import FOUNDERS, Genome, fingerprint, mutate


def allocate(irs: dict[str, float], statuses: dict[str, str]) -> dict[str, float]:
    """Birth: equal weight. After: weight ∝ max(0, IR); WEAKENED additionally
    halved; renormalized. All-zero/raw-empty -> equal weight (no div-zero)."""
    ids = [k for k in irs if k in statuses]
    if not ids:
        return {}
    raw = {}
    for k in ids:
        w = max(0.0, irs.get(k, 0.0)) if irs.get(k) is not None else 0.0
        if statuses[k] == "WEAKENED":
            w *= 0.5
        raw[k] = w
    total = sum(raw.values())
    if total <= 0:
        return {k: 1.0 / len(ids) for k in ids}
    return {k: v / total for k, v in raw.items()}


def judge_round(variant_id: str, window_no: int, n_decisions: int, ir: float,
                tokens_spent: int, token_budget: int,
                death_fingerprint: str = "", source: str = "forward") -> dict:
    """Apply one judging window to a variant. Returns the transition record.

    source="forward" only: backtest streams are REFUSED (§54 — historical
    evidence never kills/promotes; use falsification harnesses for history)."""
    if source != "forward":
        raise ValueError(f"arena judges forward evidence only, got source={source!r} (R6/R8)")
    from app.evo.judge import judge_window
    v = store.get(variant_id)
    if not v:
        raise ValueError(f"unknown variant {variant_id}")
    if v["status"] == "DEAD":
        raise ValueError(f"variant {variant_id} already dead — resurrect, don't judge")
    verdict = judge_window(n_decisions, ir, tokens_spent, token_budget)
    store.log_window(variant_id, window_no, n_decisions, ir, tokens_spent,
                     verdict["verdict"])
    strikes = v["strikes"]
    if verdict["verdict"] == "clean":
        store.set_status(variant_id, "ALIVE", 0, probation=False)
        return {"variant": variant_id, "transition": "clean",
                "status": "ALIVE", "strikes": 0, "reasons": verdict["reasons"]}
    # strike path
    if v["probation"]:
        # probation re-die: immediate death, no second chance
        store.bury(variant_id, [f"w{window_no}: probation strike"] + verdict["reasons"],
                   death_fingerprint, cause="probation-strike")
        return {"variant": variant_id, "transition": "probation->DEAD",
                "status": "DEAD", "strikes": strikes + 1, "reasons": verdict["reasons"]}
    strikes += 1
    if strikes >= 2:
        store.bury(variant_id, [f"w{window_no}: second consecutive strike"] + verdict["reasons"],
                   death_fingerprint, cause="two-strike")
        return {"variant": variant_id, "transition": "WEAKENED->DEAD",
                "status": "DEAD", "strikes": strikes, "reasons": verdict["reasons"]}
    store.set_status(variant_id, "WEAKENED", strikes)
    return {"variant": variant_id, "transition": "ALIVE->WEAKENED",
            "status": "WEAKENED", "strikes": strikes, "reasons": verdict["reasons"]}


def resurrect_if_matching(live_fingerprint: str, new_id: str, name: str) -> dict | None:
    """Seed-bank resurrection on exact 3-axis fingerprint match (prereg §4).

    Admitted ON PROBATION (WEAKENED, capped allocation via allocate()).
    Returns the admission record, or None when nothing matches.
    """
    for tomb in store.seed_bank():
        if tomb["death_fingerprint"] == live_fingerprint:
            genome = Genome(**tomb["genome"]).validate()
            store.birth(new_id, name,
                        {"topK": genome.topK, "veto_strictness": genome.veto_strictness,
                         "vix_gate": genome.vix_gate, "gross_cap": genome.gross_cap,
                         "turnover_delta": genome.turnover_delta,
                         "veto_off": genome.veto_off},
                        parent_id=tomb["variant_id"],
                        gene_diff="resurrection (identical genome)",
                        probation=True)
            return {"variant": new_id, "transition": "DEAD->WEAKENED(probation)",
                    "from_tomb": tomb["variant_id"]}
    return None


def bootstrap_founders() -> dict:
    """Birth the 8 preregistered founders once (idempotent). No backtest picks.

    Idempotent by name so a restart/re-deploy never double-births. Returns the
    ids actually born plus the current living population.
    """
    store.init()
    existing = {v["name"] for v in store.living()}
    born: list[str] = []
    for name, g in FOUNDERS:
        if name in existing:
            continue
        vid = name.split("-", 1)[0]
        store.birth(vid, name, asdict(g))
        born.append(vid)
    return {"born": born, "living": [v["id"] for v in store.living()]}


def population_state() -> dict:
    """Live population + seed bank + IR-weighted allocation (frontend view)."""
    store.init()
    living = store.living()
    irs: dict[str, float | None] = {}
    for v in living:
        row = sqlite_conn().execute(
            "SELECT ir FROM evo_windows WHERE variant_id=? ORDER BY window_no DESC LIMIT 1",
            (v["id"],)).fetchone()
        irs[v["id"]] = row[0] if row else None
    statuses = {v["id"]: v["status"] for v in living}
    return {
        "living": living,
        "seed_bank": store.seed_bank(),
        "allocation": allocate(irs, statuses),
        "cap": store.MAX_LIVING,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def events_since(seq: int = 0) -> list[dict]:
    return store.events(seq)


def propose_children(parent_id: str, max_children: int = 2) -> list[dict]:
    """Mutation proposals from an ALIVE above-median parent (prereg §1).

    Returns genome dicts only — admission happens via store.birth on a death
    vacancy (one in, one out). veto_off never arises here.
    """
    v = store.get(parent_id)
    if not v:
        raise ValueError(f"unknown variant {parent_id}")
    kids = mutate(Genome(**v["genome"]), max_children=max_children)
    out = []
    for k in kids:
        d = {"topK": k.topK, "veto_strictness": k.veto_strictness,
             "vix_gate": k.vix_gate, "gross_cap": k.gross_cap,
             "turnover_delta": k.turnover_delta, "veto_off": False}
        out.append(d)
    return out
