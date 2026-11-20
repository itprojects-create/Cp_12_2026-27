"""Honest baseline + significance layer for eval reports.

The gate table answers "did we clear our own bars?" It cannot answer the
question that actually matters for the owner's goal: is the agent's result
distinguishable from chance, and does it beat trivial constant rules? Pure
functions over a stored eval report's per-scenario rows — uses only the
recorded ``label``/``action``/``fwd_ret`` (all scoring-time ground truth,
NEVER fed to agents). No network, no tokens, no LLM, no randomness except a
seeded bootstrap.

Design notes:
- Policies are (row -> action) functions so the agent and every baseline are
  scored through the exact same path as ``app/eval/run.summarize``.
- PnL matches the harness: pnl = sign*size*fwd - traded*size*ROUNDTRIP_COST.
  ``unit_pnl`` uses size=1 (size-free directional alpha); ``pnl`` uses the
  agent's own per-scenario size where available so the book is comparable.
- Significance is exact (two-sided binomial via math.comb) plus a seeded
  bootstrap CI — no scipy dependency, mirroring scripts/diagnose_calibration.py.
"""
from __future__ import annotations

import math
import random

from app.data.base import ROUNDTRIP_COST

DIRECTION = {"buy": "long", "sell": "short", "hold": "flat"}
SIGN = {"buy": 1, "sell": -1, "hold": 0}


def load_rows(report: dict) -> list[dict]:
    """Normalize a report's results into scoring rows, skipping malformed entries."""
    rows: list[dict] = []
    for r in report.get("results", []):
        if r.get("action") not in DIRECTION or r.get("label") not in DIRECTION.values():
            continue
        if r.get("fwd_ret") is None:
            continue
        rows.append({
            "instrument": r.get("instrument", "?"),
            "as_of": r.get("as_of", "?"),
            "action": r["action"],
            "size": float(r.get("size", 0.0) or 0.0),
            "label": r["label"],
            "fwd_ret": float(r["fwd_ret"]),
        })
    return rows


def _inverse(r: dict) -> str:
    return {"buy": "sell", "sell": "buy", "hold": "hold"}[r["action"]]


# The agent as recorded, plus the trivial rules any honest claim must beat.
POLICIES = {
    "agent": lambda r: r["action"],
    "always_hold": lambda r: "hold",
    "always_long": lambda r: "buy",
    "always_short": lambda r: "sell",
    "agent_inverse": _inverse,
}


def evaluate(rows: list[dict], policy, size: float | None = None) -> dict:
    """Score one policy. ``size`` overrides per-row size (None = use the row's)."""
    dec = [r for r in rows if r["label"] in ("long", "short")]
    flat = [r for r in rows if r["label"] == "flat"]
    correct = 0
    for r in dec:
        if DIRECTION[policy(r)] == r["label"]:
            correct += 1
    hold_flat = sum(1 for r in flat if policy(r) == "hold")
    traded = [r for r in rows if policy(r) != "hold"]

    def pnl(r: dict) -> float:
        act = policy(r)
        sz = r["size"] if size is None else size
        cost = ROUNDTRIP_COST if act != "hold" else 0.0
        return SIGN[act] * sz * r["fwd_ret"] - (sz * cost)

    total_pnl = sum(pnl(r) for r in rows)
    unit_pnl = sum(pnl({"size": 1.0, **{k: v for k, v in r.items() if k != "size"}}) for r in rows)
    return {
        "n": len(rows),
        "n_decisive": len(dec),
        "n_correct": correct,
        "accuracy": correct / len(dec) if dec else 0.0,
        "no_edge_hold_rate": hold_flat / len(flat) if flat else 1.0,
        "trade_rate": len(traded) / len(rows) if rows else 0.0,
        "total_pnl": total_pnl,
        "unit_pnl": unit_pnl,
    }


def binomial_pvalue(k: int, n: int, p: float = 0.5) -> float:
    """Two-sided exact binomial p-value (math.comb only, no scipy)."""
    if n <= 0:
        return 1.0
    def pmf(i: int) -> float:
        return math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    observed = pmf(k)
    return min(1.0, sum(pmf(i) for i in range(n + 1) if pmf(i) <= observed + 1e-12))


def bootstrap_ci(correct: list[int], iters: int = 5000, seed: int = 12345,
                 lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
    """Percentile bootstrap CI of accuracy. Deterministic via ``seed``."""
    if not correct:
        return (0.0, 1.0)
    rng = random.Random(seed)
    n = len(correct)
    accs = []
    for _ in range(iters):
        accs.append(sum(correct[rng.randrange(n)] for _ in range(n)) / n)
    accs.sort()
    lo_i = int(lo / 100 * (iters - 1))
    hi_i = int(hi / 100 * (iters - 1))
    return (accs[lo_i], accs[hi_i])


def compare(report: dict) -> dict:
    """Full honest comparison: every policy scored + significance on the agent.

    Verdict meanings:
    - ``beats_chance``: agent accuracy differs from 0.5 at p<0.05 AND the CI
      excludes 0.5 (two independent signals agreeing).
    - ``beats_best_constant``: agent accuracy > the best trivial constant rule
      on this same scenario set.
    """
    rows = load_rows(report)
    scores = {name: evaluate(rows, fn) for name, fn in POLICIES.items()}
    agent = scores["agent"]
    dec_actions = [r["action"] for r in rows if r["label"] in ("long", "short")]
    labels = [r["label"] for r in rows if r["label"] in ("long", "short")]
    correct_vec = [1 if DIRECTION[a] == lb else 0 for a, lb in zip(dec_actions, labels)]
    k, n = agent["n_correct"], agent["n_decisive"]
    p = binomial_pvalue(k, n) if n else 1.0
    ci = bootstrap_ci(correct_vec) if n else (0.0, 1.0)
    constants = {name: s for name, s in scores.items()
                 if name in ("always_hold", "always_long", "always_short")}
    best_name = max(constants, key=lambda nm: constants[nm]["accuracy"]) if constants else "always_hold"
    return {
        "n_rows": len(rows),
        "scores": scores,
        "agent_binomial_p_vs_0_5": p,
        "agent_accuracy_ci95": ci,
        "beats_chance": bool(n >= 8 and p < 0.05 and (ci[1] < 0.5 or ci[0] > 0.5)),
        "best_constant": best_name,
        "best_constant_accuracy": constants[best_name]["accuracy"] if constants else 0.0,
        "beats_best_constant": bool(n >= 8 and agent["accuracy"] > constants[best_name]["accuracy"]),
        "best_constant_unit_pnl": constants[best_name]["unit_pnl"] if constants else 0.0,
        "agent_unit_pnl": agent["unit_pnl"],
    }
