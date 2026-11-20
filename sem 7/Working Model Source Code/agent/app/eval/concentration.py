"""Concentration analysis: find the lucky-stock strategy before it ships (§12).

Contributions: list of {"id", "pnl", "sector"?, "year"?}. Total = sum(pnl).
A strategy that collapses without one name/year/sector is penalized heavily —
the report carries the collapsed totals, not just a score.
"""
from __future__ import annotations


def analyze(contributions: list[dict]) -> dict:
    total = sum(c["pnl"] for c in contributions)
    ranked = sorted(contributions, key=lambda c: -c["pnl"])
    n = len(ranked)

    def top_share(k: int) -> float:
        return sum(c["pnl"] for c in ranked[:k]) / total if total else 0.0

    shares = [c["pnl"] / total for c in contributions] if total else [0.0] * n
    hhi = sum(s * s for s in shares)
    by_sector: dict[str, float] = {}
    by_year: dict[str, float] = {}
    for c in contributions:
        if c.get("sector"):
            by_sector[c["sector"]] = by_sector.get(c["sector"], 0.0) + c["pnl"]
        if c.get("year"):
            by_year[str(c["year"])] = by_year.get(str(c["year"]), 0.0) + c["pnl"]

    def drop(ids: set) -> float:
        return sum(c["pnl"] for c in contributions if c["id"] not in ids)

    top_ids = [c["id"] for c in ranked]
    rep = {
        "n": n, "total": round(total, 2),
        "top_1_share": round(top_share(1), 4),
        "top_3_share": round(top_share(3), 4),
        "top_5_share": round(top_share(5), 4),
        "top_10_share": round(top_share(10), 4),
        "hhi": round(hhi, 4),
        "sector_concentration": {k: round(v / total, 4) for k, v in by_sector.items()} if total else {},
        "year_dependency": {k: round(v / total, 4) for k, v in by_year.items()} if total else {},
        "without_best": round(drop({top_ids[0]}) if top_ids else 0.0, 2) if n else 0.0,
        "without_top3": round(drop(set(top_ids[:3])), 2),
        "without_top5": round(drop(set(top_ids[:5])), 2),
    }
    if by_sector:
        top_sec = max(by_sector, key=by_sector.get)
        rep["without_top_sector"] = {"sector": top_sec,
                                     "remaining": round(total - by_sector[top_sec], 2)}
    if by_year:
        top_yr = max(by_year, key=by_year.get)
        rep["without_top_year"] = {"year": top_yr,
                                   "remaining": round(total - by_year[top_yr], 2)}
    # Verdict heuristic (transparent, not a promotion gate by itself)
    rep["single_name_dependent"] = rep["top_1_share"] >= 0.50
    rep["narrow_base"] = rep["top_5_share"] >= 0.80
    return rep
