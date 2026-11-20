"""Dual reflection over settled outcomes → veto-context text (prereg §2).

market-reflection: whipsaw rates bucketed by (regime, veto-band) — linkage
between veto context and realized outcome. decision-reflection: recent
veto/outcome pairs per ticker. Consumer is build_veto_context() only:
session log + calibration report + Day-4 foundry inputs. Frozen pipeline
prompts are never touched (no PROMPT_VERSION bump, no cache invalidation).
"""
from __future__ import annotations

from app.data.base import ROUNDTRIP_COST
from app.db import sqlite_conn

VETO_BANDS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01))


def whipsaw_label(raw_ret: float, size: float | None) -> int:
    """1 iff the trade lost money net of costs, else 0 (prereg §3)."""
    s = size if size is not None else 0.0
    return 1 if raw_ret - s * ROUNDTRIP_COST < 0 else 0


def _settled(as_of: str) -> list[dict]:
    rows = sqlite_conn().execute(
        "SELECT ticker, raw_ret, veto, regime, breadth, size FROM memory_settlements"
        " WHERE resolved_at<=? AND veto IS NOT NULL", (as_of,)).fetchall()
    return [{"ticker": r[0], "raw": r[1], "veto": r[2], "regime": r[3],
             "breadth": r[4], "size": r[5]} for r in rows]


def market_reflection(as_of: str, regime: str | None = None) -> str:
    rows = _settled(as_of)
    if regime:
        rows = [r for r in rows if r["regime"] == regime]
    if not rows:
        return "(no settled veto outcomes before as_of)"
    lines = []
    for lo, hi in VETO_BANDS:
        band = [r for r in rows if r["veto"] is not None and lo <= r["veto"] < hi]
        if not band:
            continue
        n_whip = sum(whipsaw_label(r["raw"], r["size"]) for r in band)
        lines.append(f"- veto [{lo:.2f},{hi:.2f}) under {regime or 'any regime'}:"
                     f" whipsaw {n_whip}/{len(band)}")
    return "Market reflection (settled veto outcomes, PIT-clean):\n" + "\n".join(lines)


def decision_reflection(ticker: str, as_of: str, n: int = 5) -> str:
    rows = sqlite_conn().execute(
        "SELECT trade_date, veto, regime, raw_ret, size, reflection FROM memory_settlements"
        " WHERE ticker=? AND resolved_at<=? AND veto IS NOT NULL"
        " ORDER BY resolved_at DESC LIMIT ?", (ticker, as_of, n)).fetchall()
    if not rows:
        return "(no settled decisions for ticker before as_of)"
    lines = []
    for r in rows:
        w = whipsaw_label(r[3], r[4])
        lines.append(f"- {r[0][:10]} veto={r[1]:.2f} regime={r[2]} raw={r[3]:+.1%}"
                     f" -> {'WHIPSAW' if w else 'held'}; {r[5]}")
    return f"Decision reflection for {ticker} (PIT-clean):\n" + "\n".join(lines)


def build_veto_context(ticker: str, as_of: str, regime: str, breadth: float) -> str:
    """Assembled veto context: layered recall + both reflections."""
    from app.memory.layers import recall
    mems = recall(f"{ticker} {regime} veto breadth", as_of)
    mem_lines = "\n".join(f"- [{m['layer']}:{m['score']:.2f}] {m['content']}" for m in mems)
    return ("\n".join([
        f"Veto context for {ticker} as_of={as_of[:10]} regime={regime} breadth={breadth:.2f}:",
        "Recalled memory:",
        mem_lines or "- (none)",
        market_reflection(as_of, regime),
        decision_reflection(ticker, as_of),
    ]))
