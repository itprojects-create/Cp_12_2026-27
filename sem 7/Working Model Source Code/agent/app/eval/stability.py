"""Parameter stability: neighborhoods, sensitivity, rank stability (§19).

metrics: {param_value: metric} over an ORDERED grid. An edge that exists only
at one isolated grid point is suspicious — reported, never smoothed away.
"""
from __future__ import annotations


def analyze(grid: list, metrics: dict) -> dict:
    """grid: ordered param values; metrics: value -> metric (all grid covered)."""
    missing = [g for g in grid if g not in metrics]
    if missing:
        raise ValueError(f"stability grid incomplete, missing {missing}")
    vals = [metrics[g] for g in grid]
    best_i = max(range(len(vals)), key=lambda i: vals[i])
    # local sensitivity: worst drop from best within ±1 grid step
    neigh = []
    if best_i > 0:
        neigh.append(vals[best_i] - vals[best_i - 1])
    if best_i < len(vals) - 1:
        neigh.append(vals[best_i] - vals[best_i + 1])
    # rank stability: fraction of grid points with metric > 0 (sign robustness)
    positive = sum(1 for v in vals if v > 0) / len(vals)
    # isolated peak: best strictly positive while BOTH neighbors <= 0
    left_ok = best_i == 0 or vals[best_i - 1] <= 0
    right_ok = best_i == len(vals) - 1 or vals[best_i + 1] <= 0
    isolated = vals[best_i] > 0 and left_ok and right_ok and len(vals) > 1
    return {"best": grid[best_i], "best_metric": vals[best_i],
            "neighbor_excess": [round(x, 6) for x in neigh],
            "max_neighbor_drop": round(max(neigh) if neigh else 0.0, 6),
            "positive_fraction": round(positive, 4),
            "isolated_peak": isolated}
