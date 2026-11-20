"""Isotonic calibration (PAVA) + fractional-Kelly gate, veto-only (prereg §4).

SIZING-ONLY (binding, see data/evaluation_gates.md): calibrated probabilities
feed POSITION SCALE and nothing else. The Model audit proved isotonic maps
compress ranked signals and HURT selection (Sharpe 1.317→0.875, calibrator
discarded for ranking) — any ranking/selection/veto-structure use of these
outputs is a prereg-level violation. This module has no code path that ranks.

Trains ONLY on settled rows with veto IS NOT NULL (Day-6-forward data).
Below MIN_LABELED_ROWS the calibrator is identity (raw veto passes through,
flagged) — never fit noise. Output provably within [0, core_size].
"""
from __future__ import annotations

from app.data.base import ROUNDTRIP_COST
from app.db import sqlite_conn
from app.memory.reflect import whipsaw_label

MIN_LABELED_ROWS = 50  # prereg §3: below this, identity map only
KELLY_FRACTION = 0.5  # half-Kelly: sizing humility is a feature


def load_labeled(as_of: str | None = None) -> list[tuple[float, int]]:
    """(raw veto score, whipsaw label) pairs, PIT-filtered when as_of given."""
    if as_of:
        rows = sqlite_conn().execute(
            "SELECT veto, raw_ret, size FROM memory_settlements"
            " WHERE veto IS NOT NULL AND resolved_at<=?", (as_of,)).fetchall()
    else:
        rows = sqlite_conn().execute(
            "SELECT veto, raw_ret, size FROM memory_settlements WHERE veto IS NOT NULL").fetchall()
    return [(float(v), whipsaw_label(float(r), s)) for v, r, s in rows]


def pava_fit(pairs: list[tuple[float, int]]) -> dict:
    """Pool-Adjacent-Violators isotonic regression: monotone non-decreasing
    stepwise map. Pure python, deterministic. Returns {xs, ys} level sets."""
    if not pairs:
        return {"xs": [], "ys": [], "trained": False}
    agg: dict[float, list[int]] = {}
    for x, y in pairs:
        agg.setdefault(x, []).append(y)
    xs = sorted(agg)
    # blocks: [x_lo, x_hi, sum_y, count]
    blocks = [[x, x, float(sum(agg[x])), float(len(agg[x]))] for x in xs]
    out: list[list[float]] = []
    for b in blocks:
        out.append(b)
        while len(out) >= 2 and out[-2][2] / out[-2][3] > out[-1][2] / out[-1][3] + 1e-12:
            a, c = out.pop(), out.pop()
            out.append([c[0], a[1], c[2] + a[2], c[3] + a[3]])
    return {"xs": [b[0] for b in out], "ys": [b[2] / b[3] for b in out], "trained": True}


def fit() -> dict:
    pairs = load_labeled()
    if len(pairs) < MIN_LABELED_ROWS:
        return {"xs": [], "ys": [], "trained": False, "n": len(pairs)}
    m = pava_fit(pairs)
    m["n"] = len(pairs)
    return m


def predict(calib: dict, x: float) -> float:
    """Stepwise lookup with [0,1] clamp. Untrained map = identity (prereg §4)."""
    if not calib.get("trained"):
        return min(1.0, max(0.0, x))
    xs, ys = calib["xs"], calib["ys"]
    best = ys[0]
    for xi, yi in zip(xs, ys):
        if x >= xi:
            best = yi
    return min(1.0, max(0.0, best))


def brier(pairs: list[tuple[float, int]], probs: list[float]) -> float:
    return sum((p - y) ** 2 for (_, y), p in zip(pairs, probs)) / len(pairs)


def payoff_ratio(labeled: list[tuple[float, int]], raws: list[float]) -> float:
    """avg_win/avg_loss over labeled rows (raw returns carried alongside).

    Caller passes raw returns aligned with labeled pairs. Zero/negative
    denominator -> conservative fallback is handled in kelly_fraction.
    """
    wins = [r for (_, y), r in zip(labeled, raws) if y == 0]
    losses = [-r for (_, y), r in zip(labeled, raws) if y == 1]
    if not wins or not losses:
        return 1.0
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def kelly_fraction(p_win: float, avg_win: float, avg_loss: float,
                   frac: float = KELLY_FRACTION) -> float:
    """Half-Kelly fraction in [0,1]. No observed losses -> capped at frac
    (unbounded Kelly is not a sizing plan). Never negative, never > 1."""
    if not (0.0 <= p_win <= 1.0) or avg_win <= 0:
        return 0.0
    if avg_loss <= 0:
        return min(1.0, frac)
    b = avg_win / avg_loss
    f_star = ((p_win * b - (1 - p_win)) / b) * frac
    return min(1.0, max(0.0, f_star))


def apply_sizing(core_size: float, raw_veto: float, calib: dict,
                 avg_win: float, avg_loss: float) -> dict:
    """Veto-only sizing: size in [0, core_size], never increases (prereg §4).

    Kelly gate: non-positive edge expectation -> full veto regardless of map.
    """
    v_cal = predict(calib, raw_veto)
    f = kelly_fraction(1 - v_cal, avg_win, avg_loss)
    if f <= 0:
        return {"veto": 1.0, "size": 0.0, "v_cal": v_cal, "kelly": f, "gated": True}
    size = core_size * (1 - v_cal)
    size = min(core_size, max(0.0, size))
    return {"veto": round(v_cal, 4), "size": size, "v_cal": v_cal, "kelly": f, "gated": False}
