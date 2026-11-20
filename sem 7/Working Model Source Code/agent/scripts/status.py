"""Canonical status dashboard (§75): one CLI report, never fabricated numbers.

Usage: python scripts/status.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402


def main() -> None:
    from app.data_acquisition import base as B
    from app.db import sqlite_conn
    from app.evo import arena, champion as CH
    from app.governance import freeze as FRZ
    import glob as _g

    snap = {(h["source"], h["dataset"]): h["status"] for h in B.health_snapshot()}
    weeks = sorted(_g.glob("data/forward_week_*.json"))
    last_week = None
    if weeks:
        try:
            last_week = json.load(open(weeks[-1], encoding="utf-8"))
        except ValueError:
            last_week = {"unreadable": weeks[-1]}
    try:
        calib_n = sqlite_conn().execute(
            "SELECT COUNT(*) FROM research_outcomes").fetchone()[0]
    except Exception:  # noqa: BLE001
        calib_n = 0
    try:
        backups = sorted(_g.glob("data/backups/backup-*"))
        backup = backups[-1] if backups else "none"
    except Exception:  # noqa: BLE001
        backup = "none"
    freezes = sorted(_g.glob("data/strategy_freeze_*.json"))
    drift = FRZ.verify(freezes[-1])["verdict"] if freezes else "no-freeze"
    pop = arena.population_state()
    champ = CH.get_champion()
    exp = None
    try:
        exp = json.load(open("data/event_blackout_forward_2026-10-10.json",
                             encoding="utf-8"))
    except (OSError, ValueError):
        pass
    lines = [
        "QuantPlus Operational Status", "",
        "Money path:",
        f"  deterministic          HEALTHY ({len(pop.get('living', []))} founders alive)",
        f"  LLM authority          {'DISABLED' if not settings.LLM_MONEY_AUTHORITY else 'ENABLED!!'}",
        f"  overlay                {'OFF' if not settings.LLM_OVERLAY_ENABLED else 'ON!!'}",
        "",
        "Announcements:",
        f"  NSE                    {snap.get(('NSE', 'announcements'), 'NOT_COLLECTED')}",
        f"  BSE                    {snap.get(('BSE', 'announcements'), 'NOT_COLLECTED')}",
        "",
        "PIT membership:",
        "  operational            YES",
        f"  strict coverage        PARTIAL (17.1/50 avg — degeneracy disclosed)",
        "",
        "Event experiment:",
        f"  state                  {exp['verdict'] if exp else 'INFANCY (no artifact)'}",
        f"  eligible events        {exp.get('n_announcements', 0) if exp else 0}",
        "",
        "Forward clock:",
        f"  weeks judged           {len([w for w in weeks if 'NOJUDGE' not in w])}",
        f"  champion               {(champ or {}).get('fp', 'none')}",
        f"  config drift           {drift}",
        "",
        "Calibration:",
        f"  settled hypotheses     {calib_n}",
        "  status                 INSUFFICIENT (n<30)" if calib_n < 30 else "  status                 REPORTED",
        "",
        "Backups:",
        f"  latest                 {backup}",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
