"""Exchange market calendar (§10): trading day vs holiday/weekend/special.

Weekends are computed. Holidays/special sessions come from an operator-
maintained JSON file (data/exchange_holidays.json) — never invented in code.
Unknown weekdays with no bhavcopy are treated as UNEXPECTED_CLOSURE by the
post-close job (missing data, never fabricated expectations).
"""
from __future__ import annotations

import json
import os
from datetime import date

HOLIDAYS_PATH = os.path.join("data", "exchange_holidays.json")


def load_holidays(path: str = HOLIDAYS_PATH) -> dict:
    """{date: {kind, note}}. Missing file -> {} (weekends still enforced)."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc.get("holidays", {}) if isinstance(doc, dict) else {}


def session_kind(day_iso: str, holidays: dict | None = None) -> str:
    """NORMAL | WEEKEND | HOLIDAY | SPECIAL_MUHURAT | SPECIAL (default NORMAL
    for weekdays; operator file overrides)."""
    d = date.fromisoformat(day_iso[:10])
    entry = (holidays if holidays is not None else load_holidays()).get(d.isoformat())
    if entry:
        kind = str(entry.get("kind", "HOLIDAY")).upper()
        if kind in ("HOLIDAY", "SPECIAL_MUHURAT", "SPECIAL"):
            return kind
        return "HOLIDAY"
    if d.weekday() >= 5:
        return "WEEKEND"
    return "NORMAL"


def is_trading_day(day_iso: str, holidays: dict | None = None) -> bool:
    return session_kind(day_iso, holidays) in ("NORMAL", "SPECIAL_MUHURAT", "SPECIAL")


def expected_eod(day_iso: str, holidays: dict | None = None) -> bool:
    """Whether EOD bhavcopy should exist (Muhurat sessions publish too)."""
    return is_trading_day(day_iso, holidays)
