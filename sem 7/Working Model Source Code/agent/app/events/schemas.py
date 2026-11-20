"""Announcement schemas: structured events, never trade instructions."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EventType = Literal["BOARD_MEETING", "EARNINGS", "DIVIDEND", "SPLIT_BONUS",
                    "MERGER", "FUNDRAISING", "REGULATORY", "LEADERSHIP",
                    "OTHER"]

# Payload keys that prove an extraction tried to command capital — rejected.
FORBIDDEN_KEYS = ("action", "order", "quantity", "weight", "leverage",
                  "target_price", "stop_loss", "position", "direction")


class Announcement(BaseModel):
    model_config = {"frozen": True}
    source: str = Field(pattern="^(NSE|BSE|FILE)$")
    symbol: str = Field(min_length=1, max_length=32)
    event_type: EventType
    earnings_related: bool = False
    dividend_related: bool = False
    fundraising_related: bool = False
    merger_related: bool = False
    regulatory_related: bool = False
    severity: float = Field(ge=0.0, le=1.0)
    source_timestamp: datetime
    effective_timestamp: datetime
    blackout_candidate: bool = False
    uncertain: bool = False

    @field_validator("effective_timestamp")
    @classmethod
    def _effective_not_before_source(cls, v: datetime, info) -> datetime:
        src = info.data.get("source_timestamp")
        if src is not None and v < src:
            raise ValueError("effective_timestamp cannot precede source_timestamp "
                             "(timestamp leakage guard)")
        return v


class Extraction(BaseModel):
    """What the LLM may emit: event content ONLY. Identity and timestamps ride
    on the deterministic record and can never be overridden (see
    classify.to_announcement)."""
    model_config = {"frozen": True, "extra": "forbid"}
    event_type: EventType = "OTHER"
    earnings_related: bool = False
    dividend_related: bool = False
    fundraising_related: bool = False
    merger_related: bool = False
    regulatory_related: bool = False
    severity: float = Field(default=0.2, ge=0.0, le=1.0)
    blackout_candidate: bool = False
    uncertain: bool = False


EXTRACTION_FIELDS = frozenset(Extraction.model_fields)


def validate_extraction(payload: dict) -> Extraction:
    """Schema gate for LLM extraction output (§24). Rejects trade-directive
    payloads AND schema violations. Returns the validated Extraction —
    identity/timestamps are NOT part of it and cannot be smuggled through."""
    if not isinstance(payload, dict):
        raise ValueError("extraction must be a JSON object")
    hits = [k for k in payload if k.lower() in FORBIDDEN_KEYS]
    if hits:
        raise ValueError(f"extraction carries capital directives {hits} — rejected, "
                         "LLM extraction must never produce orders (R1)")
    return Extraction(**payload)
