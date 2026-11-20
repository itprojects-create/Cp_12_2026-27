"""Blackout engine: deterministic consequence of classified announcements.

blackout_at(symbol, as_of, announcements, pre, post): True when a
blackout_candidate announcement for the symbol has effective_timestamp within
[as_of - post, as_of + pre] days (pre = days BEFORE the event to stand down,
post = days after). Mirrors foundry blackout_window ranges (pre 0..5, post 0..3).

No announcements -> (False, "unavailable") — abstention with provenance (§25),
never an imputed blackout and never imputed safety.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

BLACKOUT_FAMILY_VERSION = "BLACKOUT_FAMILY_V1"


class BlackoutRule(BaseModel):
    """Versioned blackout rule (§28). Shrink-only by construction (§72):
    applies_to_entries/increases may block; mandatory risk exits are NEVER
    blocked (enforced in apply_to_position, tested)."""
    model_config = {"frozen": True}
    rule_id: str = Field(min_length=1, max_length=16)
    taxonomy_version: str = "EVENT_TAXONOMY_V1"
    eligible_event_types: frozenset = frozenset({"BOARD_MEETING", "EARNINGS"})
    pre_event_sessions: int = Field(ge=0, le=5)
    post_event_sessions: int = Field(ge=0, le=3)
    severity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    applies_to_entries: bool = True
    applies_to_exits: bool = False
    applies_to_existing_positions: bool = False
    version: str = BLACKOUT_FAMILY_VERSION

    def frozen_dict(self) -> dict:
        """Byte-stable serialization for the frozen family artifact: sets sort."""
        d = self.model_dump(mode="json")
        d["eligible_event_types"] = sorted(d["eligible_event_types"])
        return d


# Frozen candidate family (§29, predeclared before forward outcomes):
# B0 no-blackout control; B1 event session only; B2 +next session; B3 two-session.
BLACKOUT_FAMILY_V1: tuple[BlackoutRule, ...] = (
    BlackoutRule(rule_id="B0", pre_event_sessions=0, post_event_sessions=0,
                 applies_to_entries=False),
    BlackoutRule(rule_id="B1", pre_event_sessions=0, post_event_sessions=0),
    BlackoutRule(rule_id="B2", pre_event_sessions=0, post_event_sessions=1),
    BlackoutRule(rule_id="B3", pre_event_sessions=1, post_event_sessions=1),
)


def rule_to_dsl(rule: BlackoutRule) -> dict:
    """Bridge to the Strategy DSL EVENT_BLACKOUT op (B0 = empty program)."""
    if rule.rule_id == "B0" or not rule.applies_to_entries:
        return {"ops": []}
    return {"ops": [{"op": "EVENT_BLACKOUT",
                     "params": {"pre": rule.pre_event_sessions,
                                "post": rule.post_event_sessions}}]}


def _eff(a) -> datetime:
    eff = a.effective_timestamp if hasattr(a, "effective_timestamp") else a["effective_timestamp"]
    return datetime.fromisoformat(eff) if isinstance(eff, str) else eff


def _etype(a) -> str:
    from app.events import taxonomy as TAX
    raw = a.event_type if hasattr(a, "event_type") else a.get("event_type", "OTHER")
    return TAX.from_legacy(raw)


def rule_active(rule: BlackoutRule, symbol: str, as_of: datetime,
                announcements: list) -> tuple[bool, str]:
    """Deterministic rule evaluation: any eligible blackout_candidate in window.

    Session granularity: dates (not datetimes) are compared — the event session
    is the event's calendar date, [as_of-post, as_of+pre] in whole sessions."""
    if not rule.applies_to_entries:
        return False, f"control {rule.rule_id}: blackout never applies"
    sym = symbol.upper()
    lo = as_of.date().toordinal() - rule.post_event_sessions
    hi = as_of.date().toordinal() + rule.pre_event_sessions
    for a in announcements:
        name = (a.symbol if hasattr(a, "symbol") else a.get("symbol", "")).upper()
        if name != sym:
            continue
        bc = a.blackout_candidate if hasattr(a, "blackout_candidate") else a.get("blackout_candidate")
        if not bc:
            continue
        if _etype(a) not in rule.eligible_event_types:
            continue
        sev = a.severity if hasattr(a, "severity") else a.get("severity", 0.0)
        if rule.severity_threshold is not None and sev < rule.severity_threshold:
            continue
        if lo <= _eff(a).date().toordinal() <= hi:
            return True, f"blackout {rule.rule_id}: eligible event in window"
    if not any(((a.symbol if hasattr(a, "symbol") else a.get("symbol", "")).upper() == sym)
               for a in announcements):
        return False, "unavailable: no announcements for symbol"
    return False, f"no eligible event in {rule.rule_id} window"


def apply_to_position(current: float, proposed: float,
                      blackout_active: bool) -> float:
    """Shrink-only application (§§71-72): blackout may block NEW risk (entries,
    increases) but NEVER blocks decreases/exits and NEVER creates exposure.
    current/proposed are signed weights (long-only >= 0 in this system)."""
    if not blackout_active:
        return proposed
    if proposed <= 0.0 or current <= 0.0:
        # nothing held or full exit proposed: exits are never blocked
        return min(proposed, current) if current > 0 else 0.0
    # position held and blackout on: cap at current (no increases), allow cuts
    return min(proposed, current)


def blackout_at(symbol: str, as_of: datetime,
                announcements: list,
                pre: int = 2, post: int = 1) -> tuple[bool, str]:
    """announcements: Announcement objects (or dicts with the same keys)."""
    if not 0 <= pre <= 5 or not 0 <= post <= 3:
        raise ValueError("blackout window pre 0..5 / post 0..3 (foundry ranges)")
    sym = symbol.upper()
    relevant = [a for a in announcements
                if (a.symbol if hasattr(a, "symbol") else a.get("symbol", "")).upper() == sym]
    if not relevant:
        return False, "unavailable: no announcements for symbol"
    hits = []
    for a in relevant:
        eff = a.effective_timestamp if hasattr(a, "effective_timestamp") else a["effective_timestamp"]
        if isinstance(eff, str):
            eff = datetime.fromisoformat(eff)
        bc = a.blackout_candidate if hasattr(a, "blackout_candidate") else a.get("blackout_candidate")
        if bc and (as_of - timedelta(days=post)) <= eff <= (as_of + timedelta(days=pre)):
            hits.append(a)
    if hits:
        return True, f"blackout: {len(hits)} candidate(s) in -{post}/+{pre}d window"
    return False, "no candidate in window"


def dsl_row_flag(symbol: str, as_of: datetime, announcements: list,
                 pre: int = 2, post: int = 1) -> dict:
    """Row context for the EVENT_BLACKOUT DSL op + provenance."""
    flag, reason = blackout_at(symbol, as_of, announcements, pre, post)
    return {"blackout": flag, "provenance": reason}
