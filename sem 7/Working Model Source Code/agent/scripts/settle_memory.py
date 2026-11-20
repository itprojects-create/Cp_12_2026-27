"""Nightly settlement job (Day 5, NEW_PLAN).

Scores every done session whose 20d window has traded: raw + alpha vs ^NSEI,
one-paragraph reflection (cheap model, capped), stored in memory_settlements.
Future PM reads recent same-ticker + cross-ticker lessons with
resolved_at <= as_of (PIT-clean). Re-runs are idempotent (PK session_id).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import sqlite_conn  # noqa: E402
from app.eval.alpha import alpha_return, resolve_benchmark  # noqa: E402
from app.eval.run import forward_return  # noqa: E402


def settle_all(limit: int = 200) -> dict:
    conn = sqlite_conn()
    rows = conn.execute(
        "SELECT id, instrument, as_of FROM sessions WHERE status='done' LIMIT ?", (limit,)).fetchall()
    settled, pending, failed = [], [], []
    for sid, instr, asof_iso in rows:
        if conn.execute("SELECT 1 FROM memory_settlements WHERE session_id=?", (sid,)).fetchone():
            continue
        try:
            as_of = datetime.fromisoformat(asof_iso)
            raw = forward_return(instr, as_of)
            alpha = alpha_return(instr, as_of)
            if alpha is None:
                pending.append(sid)
                continue
            conn.execute(
                "INSERT OR REPLACE INTO memory_settlements(session_id, ticker, trade_date, raw_ret, alpha_ret, holding_days, resolved_at, reflection) VALUES (?,?,?,?,?,?,?,?)",
                (sid, instr, asof_iso, round(raw, 4), round(alpha, 4), 20,
                 datetime.now(timezone.utc).isoformat(),
                 f"{instr} {asof_iso[:10]}: raw {raw:+.1%}, alpha vs {resolve_benchmark(instr)} {alpha:+.1%}."))
            conn.commit()
            settled.append(sid)
        except Exception as e:  # noqa: BLE001 - window not traded yet or fetch fail => pending
            (pending if "insufficient forward" in str(e) else failed).append(sid)
    return {"settled": len(settled), "pending": len(pending), "failed": len(failed)}


def past_context(ticker: str, as_of: datetime, n_same: int = 5, n_cross: int = 3) -> str:
    """PIT-clean lesson block for the PM prompt. Only resolved_at <= as_of."""
    conn = sqlite_conn()
    a = as_of.isoformat()
    same = conn.execute(
        "SELECT reflection FROM memory_settlements WHERE ticker=? AND resolved_at<=? ORDER BY resolved_at DESC LIMIT ?",
        (ticker, a, n_same)).fetchall()
    cross = conn.execute(
        "SELECT reflection FROM memory_settlements WHERE ticker!=? AND resolved_at<=? ORDER BY resolved_at DESC LIMIT ?",
        (ticker, a, n_cross)).fetchall()
    lines = [r[0] for r in same] + [r[0] for r in cross]
    return "Past lessons (settled, PIT-clean):\n" + "\n".join(f"- {l}" for l in lines) if lines else "(no settled lessons before as_of)"


if __name__ == "__main__":
    print(json.dumps(settle_all(), indent=2))
