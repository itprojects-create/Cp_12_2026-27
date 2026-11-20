"""Versioned rubric for issuer-event classification questions (System One).

Freeze policy: the rubric is frozen BEFORE any evaluation; ``RUBRIC_SHA256``
binds every classification to the exact question text. Question wording is
blind to market outcomes: no question mentions prices, returns, directions,
ports, targets or any expected share-price movement. A future rubric change
must create ``events_ai_rubric/2`` — never edit this one.

Unknown/none policy: ``event_type`` carries an explicit ``none`` option; a
classification whose top option probability falls below the review threshold
goes to NEEDS_REVIEW rather than being silently accepted.
"""
from __future__ import annotations

from quantplus_intelligence.research_v3.events_ai.contracts import (
    canonical_json, sha256_text)

RUBRIC_VERSION = "events_ai_rubric/1"

EVENT_TYPE_OPTIONS: dict[str, str] = {
    "financial_results": "Audited or unaudited financial results or results schedule outcome",
    "guidance_change": "Explicit revision of previously communicated forward guidance",
    "governance": "Auditor, promoter, board, management or regulatory event",
    "contract": "Confirmed contract, order win or order award",
    "capital_action": "Capital issue, buyback, delisting, merger or restructuring step",
    "other": "Another explicit issuer fact that fits no option above",
    "none": "No explicit issuer event is supported by the excerpt",
}

MATERIALITY_LEVELS: tuple[str, ...] = (
    "Administrative or no material issuer fact",
    "Routine announcement without new substantive facts",
    "Potentially consequential issuer development",
    "Major consequential issuer development",
    "Exceptional confirmed issuer development",
)

REVIEW_CONFIDENCE_THRESHOLD = 0.6   # below this → NEEDS_REVIEW (never silently accepted)


def _event_type_question() -> dict:
    return {
        "type": "choice",
        "instructions": (
            "Classify only explicit issuer facts stated in official_excerpt. "
            "Judge the announcement text only; never predict stock returns, "
            "never infer facts that are not written. If the excerpt is "
            "ambiguous or supports no event, choose none."
        ),
        "criteria": dict(EVENT_TYPE_OPTIONS),
    }


def _guidance_question() -> dict:
    return {
        "type": "noul",
        "instructions": (
            "Does the excerpt explicitly state that previously communicated "
            "forward guidance has changed? Answer true only when a change to "
            "earlier communicated guidance is written in the excerpt; silent "
            "absence of guidance is false."
        ),
        "criteria": {
            "true": "The excerpt explicitly states a change to previously communicated guidance",
            "false": "No explicit guidance change is stated in the excerpt",
        },
    }


def _materiality_question() -> dict:
    return {
        "type": "score",
        "instructions": (
            "Rate the factual importance of this issuer announcement on the "
            "given scale. Rate issuer-event importance only; do not rate "
            "expected market reaction or share-price direction."
        ),
        "criteria": list(MATERIALITY_LEVELS),
    }


def build_questions() -> dict:
    """The exact SystemOne ``questions`` object for the frozen rubric."""
    return {
        "event_type": _event_type_question(),
        "explicit_guidance_change": _guidance_question(),
        "materiality": _materiality_question(),
    }


def rubric_sha256() -> str:
    return sha256_text(canonical_json(build_questions()))
