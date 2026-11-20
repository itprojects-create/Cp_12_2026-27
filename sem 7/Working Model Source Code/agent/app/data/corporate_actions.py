"""Corporate-action PIT: schema + coverage marking (P7, §66).

No verified source history is available in this repo, so this module defines
the schema, tracks coverage per symbol/period, and marks everything else
UNKNOWN — integrated only where verified. Split/bonus/right/dividend/merger/
symbol-change/delisting adjustments with effective dates; unknown periods
abstain (adjustment factor 1.0 + UNKNOWN status, never an imputed adjustment).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.db import sqlite_conn

SCHEMA_VERSION = "corpact-v1"
KINDS = ("split", "bonus", "rights", "dividend", "merger",
         "symbol_change", "delisting")


class CorporateAction(BaseModel):
    model_config = {"frozen": True}
    symbol: str = Field(min_length=1, max_length=32)
    kind: str
    effective_date: str  # YYYY-MM-DD
    factor: float = Field(gt=0.0)  # price multiplier on/after effective_date
    old_symbol: str | None = None
    new_symbol: str | None = None
    source: str = "UNVERIFIED"
    verified: bool = False

    def validate_kind(self) -> "CorporateAction":
        if self.kind not in KINDS:
            raise ValueError(f"unknown corporate-action kind {self.kind!r}")
        if len(self.effective_date) != 10:
            raise ValueError("effective_date must be YYYY-MM-DD")
        return self


def init_tables() -> None:
    sqlite_conn().execute("""CREATE TABLE IF NOT EXISTS corporate_actions
        (symbol TEXT, kind TEXT, effective_date TEXT, factor REAL,
         old_symbol TEXT, new_symbol TEXT, source TEXT, verified INTEGER,
         PRIMARY KEY (symbol, kind, effective_date))""")
    sqlite_conn().commit()


def record(action: CorporateAction) -> None:
    action.validate_kind()
    init_tables()
    a = action
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO corporate_actions(symbol, kind, effective_date, factor,"
        " old_symbol, new_symbol, source, verified) VALUES (?,?,?,?,?,?,?,?)",
        (a.symbol.upper(), a.kind, a.effective_date, a.factor, a.old_symbol,
         a.new_symbol, a.source, 1 if a.verified else 0))
    sqlite_conn().commit()


def adjustment_factor(symbol: str, date_iso: str) -> tuple[float, str]:
    """Cumulative verified adjustment factor for date. Unknown periods abstain:
    (1.0, 'UNKNOWN') when no verified rows cover the symbol — never imputed."""
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT factor FROM corporate_actions WHERE symbol=? AND effective_date <= ?"
        " AND verified=1 ORDER BY effective_date", (symbol.upper(), date_iso[:10])).fetchall()
    any_rows = sqlite_conn().execute(
        "SELECT COUNT(*) FROM corporate_actions WHERE symbol=?", (symbol.upper(),)).fetchone()[0]
    if not any_rows:
        return 1.0, "UNKNOWN"
    factor = 1.0
    for r in rows:
        factor *= float(r[0])
    return factor, "VERIFIED"


def coverage(symbols: list[str]) -> dict:
    """Per-symbol coverage: verified-action count + status."""
    init_tables()
    out = {}
    for s in symbols:
        n = sqlite_conn().execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE symbol=? AND verified=1",
            (s.upper(),)).fetchone()[0]
        out[s] = {"verified_actions": n,
                  "status": "VERIFIED" if n else "UNKNOWN"}
    return out
