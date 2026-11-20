"""Perturbation robustness: PC/CI/IDS on veto decisions (Day-5 prereg §3).

Profit-Mirage-adapted, documented differences: our functions are deterministic,
so PC measures decision-flip rate under input dust (not memory leakage); IDS>0
proves the veto is input-driven rather than a memorized constant. Thresholds:
PC >= 0.85 gate; CI reported only; IDS strictly > 0 gate. Constant-function
control must yield PC=1.0, IDS=0 (suite validity check).
"""
from __future__ import annotations

import random

PC_GATE = 0.85


def _jitter(x: float, eps: float, rng: random.Random) -> float:
    return x * (1 + rng.uniform(-eps, eps))


def suite(decision_fn, grid: list[dict], eps: float = 0.01, n_noise: int = 8,
          seed: int = 7) -> dict:
    """decision_fn(row) -> float veto in [0,1]. Binary call: veto<0.5 vs >=0.5."""
    rng = random.Random(seed)
    base = [decision_fn(r) for r in grid]
    flips, out_std, sens_num, sens_den = 0, [], 0.0, 0.0
    total = 0
    for r, b in zip(grid, base):
        outs = []
        for _ in range(n_noise):
            noisy = {}
            for k, v in r.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    noisy[k] = _jitter(float(v), eps, rng)
                else:
                    noisy[k] = v
            outs.append(decision_fn(noisy))
        b_call = b >= 0.5
        flips += sum(1 for o in outs if (o >= 0.5) != b_call)
        total += len(outs)
        mu = sum(outs) / len(outs)
        out_std.append(sum((o - mu) ** 2 for o in outs) / len(outs))
        sens_num += sum(abs(o - b) for o in outs) / len(outs)
    # IDS denominator: mean |input| perturbation magnitude across numeric fields
    din = []
    rng2 = random.Random(seed)
    for r in grid:
        for _ in range(n_noise):
            din.append(sum(abs(_jitter(float(v), eps, rng2) - float(v))
                           for k, v in r.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)))
    sens_den = sum(din) / len(din) if din else 0.0
    pc = 1 - flips / total if total else 1.0
    ci = 1 - (sum(out_std) / len(out_std)) ** 0.5 / 0.5 if out_std else 1.0
    ids = (sens_num / (len(grid) * n_noise)) / sens_den if sens_den > 0 else 0.0
    fire_rate = sum(1 for b in base if b > 0) / len(base) if base else 0.0
    return {"PC": round(pc, 4), "CI": round(ci, 4), "IDS": round(ids, 4),
            "pc_gate": pc >= PC_GATE, "ids_gate": ids > 0, "n": len(grid),
            "fire_rate": round(fire_rate, 4),
            "nondegenerate": 0.0 < fire_rate < 1.0}


def veto_row_fn(veto_fn, regime: str, breadth: float):
    """Adapt veto_fraction(regime, breadth, ret_5d, dist_hi) to row-decisions."""
    def fn(row: dict) -> float:
        return veto_fn(regime, breadth, row["ret_5d"], row["dist_hi"],
                       row.get("blackout", False))
    return fn
