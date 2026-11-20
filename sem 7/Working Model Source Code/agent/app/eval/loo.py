"""Leave-one-out utilities: stock/sector/year/regime/top-contributor (§21).

Generic engine + thin wrappers. metric_fn maps a surviving item list to a
scalar (e.g. total pnl, Sharpe). Expensive variants run only on finalists —
the module is cheap; the caller decides the shortlist.
"""
from __future__ import annotations

from collections.abc import Callable


def drop_one_out(items: list[dict], key_fn: Callable[[dict], str],
                 metric_fn: Callable[[list[dict]], float]) -> dict:
    """For each distinct key: metric without that group. Plus no-drop baseline."""
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(key_fn(it), []).append(it)
    base = metric_fn(items)
    per_drop = {}
    for key in sorted(groups):
        rest = [it for it in items if key_fn(it) != key]
        per_drop[key] = metric_fn(rest)
    worst_key = min(per_drop, key=per_drop.get) if per_drop else None
    return {"baseline": base, "per_drop": per_drop, "worst_drop": worst_key,
            "worst_value": per_drop.get(worst_key) if worst_key else None,
            "n_groups": len(groups)}


def total_pnl(items: list[dict]) -> float:
    return sum(float(i.get("pnl", 0.0)) for i in items)


def leave_one_stock_out(items: list[dict]) -> dict:
    return drop_one_out(items, lambda i: str(i["id"]), total_pnl)


def leave_one_sector_out(items: list[dict]) -> dict:
    return drop_one_out(items, lambda i: str(i.get("sector", "UNKNOWN")), total_pnl)


def leave_one_year_out(items: list[dict]) -> dict:
    return drop_one_out(items, lambda i: str(i.get("year", "UNKNOWN")), total_pnl)


def leave_one_regime_out(items: list[dict]) -> dict:
    return drop_one_out(items, lambda i: str(i.get("regime", "UNKNOWN")), total_pnl)


def leave_top_contributor_out(items: list[dict]) -> dict:
    if not items:
        return {"baseline": 0.0, "remaining": 0.0, "top": None}
    top = max(items, key=lambda i: float(i.get("pnl", 0.0)))
    rest = [i for i in items if i is not top]
    return {"baseline": total_pnl(items), "remaining": total_pnl(rest),
            "top": top.get("id"), "top_share": (top.get("pnl", 0.0) / total_pnl(items)
                                                if total_pnl(items) else 0.0)}
