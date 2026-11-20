"""Versioned event taxonomy (P2, §22).

EVENT_TAXONOMY_V1: fixed category meanings. Never silently change a category —
a new taxonomy version supersedes with a migration note. from_legacy() maps
the pre-existing Announcement event types forward.
"""
from __future__ import annotations

VERSION = "EVENT_TAXONOMY_V1"

TAXONOMY_V1: tuple[str, ...] = (
    "EARNINGS", "BOARD_MEETING", "DIVIDEND", "BUYBACK", "SPLIT", "BONUS",
    "RIGHTS", "FUNDRAISING", "DEBT", "M_AND_A", "ORDER_WIN", "ORDER_LOSS",
    "REGULATORY", "LEGAL", "MANAGEMENT_CHANGE", "AUDITOR", "SHAREHOLDER",
    "INSIDER", "CORPORATE_ACTION", "OTHER", "UNKNOWN",
)

_LEGACY_MAP = {
    "EARNINGS": "EARNINGS", "BOARD_MEETING": "BOARD_MEETING",
    "DIVIDEND": "DIVIDEND", "SPLIT_BONUS": "CORPORATE_ACTION",
    "MERGER": "M_AND_A", "FUNDRAISING": "FUNDRAISING",
    "REGULATORY": "REGULATORY", "LEADERSHIP": "MANAGEMENT_CHANGE",
    "OTHER": "OTHER",
}


def from_legacy(event_type: str) -> str:
    """Map a legacy Announcement event_type into the versioned taxonomy."""
    return _LEGACY_MAP.get(event_type, "UNKNOWN")


def is_valid(category: str, version: str = VERSION) -> bool:
    if version != VERSION:
        raise ValueError(f"unknown taxonomy version {version!r}")
    return category in TAXONOMY_V1
