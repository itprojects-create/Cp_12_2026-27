"""Classify: deterministic keyword rules first, LLM extraction second (§24).

Deterministic layer handles the unambiguous cases with zero inference cost.
The LLM layer (`llm_extract`, opt-in) handles ambiguous titles — its output is
schema-gated by validate_extraction, which rejects anything carrying trade
directives. Classification NEVER emits orders; it emits Announcement data.
"""
from __future__ import annotations

from datetime import datetime

from app.events.schemas import Announcement, validate_extraction

_RULES: tuple[tuple[str, dict], ...] = (
    ("board meeting", {"event_type": "BOARD_MEETING", "blackout_candidate": True,
                       "severity": 0.6}),
    ("financial results", {"event_type": "EARNINGS", "earnings_related": True,
                           "blackout_candidate": True, "severity": 0.8}),
    ("quarterly results", {"event_type": "EARNINGS", "earnings_related": True,
                           "blackout_candidate": True, "severity": 0.8}),
    ("dividend", {"event_type": "DIVIDEND", "dividend_related": True, "severity": 0.4}),
    ("bonus issue", {"event_type": "SPLIT_BONUS", "severity": 0.4}),
    ("stock split", {"event_type": "SPLIT_BONUS", "severity": 0.4}),
    ("merger", {"event_type": "MERGER", "merger_related": True, "severity": 0.7}),
    ("amalgamation", {"event_type": "MERGER", "merger_related": True, "severity": 0.7}),
    ("fund raising", {"event_type": "FUNDRAISING", "fundraising_related": True,
                      "severity": 0.5}),
    ("rights issue", {"event_type": "FUNDRAISING", "fundraising_related": True,
                      "severity": 0.5}),
    ("sebi", {"event_type": "REGULATORY", "regulatory_related": True, "severity": 0.6}),
    ("penalty", {"event_type": "REGULATORY", "regulatory_related": True, "severity": 0.6}),
    ("resignation", {"event_type": "LEADERSHIP", "severity": 0.4}),
    ("appointment", {"event_type": "LEADERSHIP", "severity": 0.3}),
)


def classify_rule(title: str) -> dict | None:
    """Deterministic keyword classification. None = ambiguous, escalate."""
    low = (title or "").lower()
    for keyword, out in _RULES:
        if keyword in low:
            return dict(out)
    return None


def triage(title: str) -> dict:
    """Abstention-first triage (§23): CLASSIFY only on a rule hit, else ABSTAIN
    with reason. Never force a category; ambiguous titles escalate to versioned
    extraction or stay abstained."""
    if not (title or "").strip():
        return {"decision": "ABSTAIN", "reason": "empty title", "rule": None}
    if len(title.strip()) < 12:
        return {"decision": "ABSTAIN", "reason": "title too short for reliable match",
                "rule": None}
    rule = classify_rule(title)
    if rule is None:
        return {"decision": "ABSTAIN",
                "reason": "ambiguous — escalate to versioned extraction or abstain",
                "rule": None}
    return {"decision": "CLASSIFY", "reason": "keyword rule hit", "rule": rule}


def to_announcement(record: dict, rule: dict | None = None,
                    llm: dict | None = None) -> Announcement:
    """Build the validated Announcement from deterministic rule and/or gated
    LLM extraction. LLM fields never override source/symbol/timestamps."""
    merged: dict = {"event_type": "OTHER", "severity": 0.2}
    if rule:
        merged.update(rule)
    if llm is not None:
        gated = validate_extraction(llm)  # raises on directives — fail closed
        merged.update({k: v for k, v in gated.model_dump().items()
                       if k not in ("source", "symbol", "source_timestamp",
                                    "effective_timestamp", "uncertain")})
        merged["uncertain"] = bool(gated.uncertain)
    src = datetime.fromisoformat(record["source_timestamp"])
    if rule is None:
        # No deterministic grounding: uncertain unless the extraction both
        # names a real event AND explicitly asserts certainty.
        llm_certain = (llm is not None and not merged.get("uncertain", True)
                       and merged.get("event_type") != "OTHER")
        merged["uncertain"] = not llm_certain
    else:
        merged["uncertain"] = bool(merged.get("uncertain", False))
    return Announcement(source=record["source"], symbol=record["symbol"],
                        effective_timestamp=datetime.fromisoformat(
                            record["effective_timestamp"]),
                        source_timestamp=src, **merged)


EXTRACTION_SYSTEM = (
    "Exchange-announcement structured extraction. Read the title and return ONLY "
    "Announcement JSON: {event_type, earnings_related, dividend_related, "
    "fundraising_related, merger_related, regulatory_related, severity (0-1), "
    "blackout_candidate, uncertain}. You MUST NOT include any trade instruction: "
    "no action/order/quantity/weight/leverage/target/stop/position/direction keys, "
    "no BUY/SELL language. Uncertain titles -> uncertain=true, low severity.")


def llm_extract(record: dict, session_id: str) -> Announcement:
    """Opt-in LLM extraction for ambiguous titles. Lazy gateway import; output
    schema-gated (validate_extraction raises on directives or bad shapes)."""
    from app.agents._util import call_json
    from pydantic import BaseModel

    class _Extraction(BaseModel):
        model_config = {"extra": "allow"}
        event_type: str = "OTHER"

    out = call_json("events_extract", session_id, EXTRACTION_SYSTEM,
                    f"[{record['source']} {record['symbol']}] {record['title']}",
                    _Extraction)
    return to_announcement(record, classify_rule(record["title"]),
                           out.model_dump())
