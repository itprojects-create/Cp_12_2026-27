"""W3 diagnostics: day-clustered rank IC, Brier/calibration, MAE.

Uncertainty rule: cross-sectional observations on ONE decision session are
one correlated group (names co-move), so every t-stat is computed on the
DAY-level IC series (n = distinct days), never on pooled rows. No spurious
significance from thousands of overlapping stock-label observations.
"""
from __future__ import annotations

import math
from collections import defaultdict


def _rank(xs: list[float]) -> list[float]:
    """Average ranks with tie handling (deterministic, no external deps)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    den = math.sqrt(sum(x * x for x in da) * sum(x * x for x in db))
    if den == 0:
        return None
    return sum(x * y for x, y in zip(da, db)) / den


def day_clustered_rank_ic(pred_by_day: dict[str, dict[str, float]],
                          label_by_day: dict[str, dict[str, float]]) -> dict:
    """Spearman rank IC per decision session + day-clustered uncertainty.

    ``pred_by_day[session][symbol] = prediction``; symbols missing from the
    label map (inadmissible labels) are dropped per day. A day needs >= 5
    paired names to contribute (thin cross-sections are disclosed, not used).
    """
    ics: list[float] = []
    per_day: dict[str, dict] = {}
    for day in sorted(set(pred_by_day) & set(label_by_day)):
        p, y = pred_by_day[day], label_by_day[day]
        common = [s for s in p if s in y]
        if len(common) < 5:
            per_day[day] = {"n": len(common), "ic": None,
                            "note": "thin cross-section (n<5) excluded"}
            continue
        ic = _pearson(_rank([p[s] for s in common]), _rank([y[s] for s in common]))
        if ic is not None:
            ics.append(ic)
            per_day[day] = {"n": len(common), "ic": round(ic, 6)}
        else:
            per_day[day] = {"n": len(common), "ic": None, "note": "degenerate"}
    n_days = len(ics)
    if n_days == 0:
        return {"n_days": 0, "mean_ic": None, "ic_t_day_clustered": None,
                "per_day": per_day,
                "note": "day-level t-stat; names within a day are one "
                        "correlated group, never pooled as independent rows"}
    mean = sum(ics) / n_days
    if n_days == 1:
        t = None
    else:
        sd = math.sqrt(sum((x - mean) ** 2 for x in ics) / (n_days - 1))
        t = None if sd == 0 else mean / (sd / math.sqrt(n_days))
    return {"n_days": n_days, "mean_ic": round(mean, 6),
            "ic_t_day_clustered": None if t is None else round(t, 4),
            "per_day": per_day,
            "note": "day-level t-stat; names within a day are one correlated "
                    "group, never pooled as independent rows"}


def brier(pred_prob_by_day: dict[str, dict[str, float]],
          y_by_day: dict[str, dict[str, int]]) -> dict:
    """Brier score + decile calibration for binary direction labels.

    Only pairs where BOTH sides exist count; the class definition is
    ``admissible label gross_return > 0`` and the base rate is reported.
    """
    pairs = [(p, y_by_day[d][s]) for d in pred_prob_by_day
             for s, p in pred_prob_by_day[d].items() if s in y_by_day.get(d, {})]
    if not pairs:
        return {"n": 0, "brier": None, "base_rate": None, "bins": []}
    n = len(pairs)
    bs = sum((p - y) ** 2 for p, y in pairs) / n
    base = sum(y for _p, y in pairs) / n
    bins = []
    for lo in range(10):
        sel = [(p, y) for p, y in pairs if lo / 10 <= p < (lo + 1) / 10
               or (lo == 9 and p == 1.0)]
        if sel:
            bins.append({"bin": f"{lo / 10:.1f}-{(lo + 1) / 10:.1f}",
                         "n": len(sel),
                         "mean_pred": round(sum(p for p, _ in sel) / len(sel), 4),
                         "empirical": round(sum(y for _, y in sel) / len(sel), 4)})
    return {"n": n, "brier": round(bs, 6), "base_rate": round(base, 4),
            "bins": bins}


def mae(pred_by_day: dict[str, dict[str, float]],
        label_by_day: dict[str, dict[str, float]]) -> dict:
    """Mean absolute error over admissible pairs (+ hit rate on direction)."""
    pairs = [(p, label_by_day[d][s]) for d in pred_by_day
             for s, p in pred_by_day[d].items() if s in label_by_day.get(d, {})]
    if not pairs:
        return {"n": 0, "mae": None, "hit_rate": None}
    n = len(pairs)
    return {"n": n, "mae": round(sum(abs(p - y) for p, y in pairs) / n, 6),
            "hit_rate": round(sum((p > 0) == (y > 0) for p, y in pairs) / n, 4)}


def group_by_day(rows: list[dict], value_key: str,
                 filter_fn=None) -> dict[str, dict[str, float]]:
    """Fold a flat [{session, symbol, value_key}] list into day maps."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        if filter_fn and not filter_fn(r):
            continue
        v = r.get(value_key)
        if v is not None:
            out[r["session"]][r["symbol"]] = v
    return dict(out)
