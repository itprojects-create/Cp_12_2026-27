"""Shared 5-tier rating vocabulary + REVIEW sentinel (Day 2 T2.2, NEW_PLAN).

Buy > Overweight > Hold > Underweight > Sell. REVIEW = unparseable output,
never silently degraded to Hold. Centralises parsing so Manager, PM and
memory log cannot drift. Adapted from TradingAgents rating.py.
"""
from __future__ import annotations

import re
import unicodedata

RATINGS_5_TIER: tuple[str, ...] = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
RATING_REVIEW = "REVIEW"

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}
_RATING_LABEL_RE = re.compile(r"(?<![a-z])rating\b[^:\-\u2010-\u2015]*[:\-\u2010-\u2015][\s*]*(\w+)",
                              re.IGNORECASE)
_OWN_QUALIFIER = r"(?:(?:final|our|overall|my|recommended|updated|revised|new|current)\s+)*"
_RATING_LINE_RE = re.compile(
    r"\s*(?P<item>(?:[-+*\u2022]|\d+[.)])\s+)?[\s*_#]*" + _OWN_QUALIFIER
    + r"rating[^\w:\-\u2010-\u2015]*[:\-\u2010-\u2015][\s*]*(?P<value>\w+)",
    re.IGNORECASE,
)
_RATING_SCALE_RE = re.compile(r"rating\s*(scale|options|legend)", re.IGNORECASE)


def extract_rating(text: str) -> str | None:
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)
    lines = [line for line in norm.splitlines() if line.strip() and not _RATING_SCALE_RE.search(line)]
    first = next((line for line in lines if not line.lstrip().startswith("#")
                  or _RATING_LINE_RE.match(line)), "")
    m = _RATING_LINE_RE.match(first)
    opening = m if m and m.group("value").lower() in _RATING_SET else None
    if opening and not opening.group("item"):
        return opening.group("value").capitalize()
    own = [opening.group("value").capitalize()] if opening else []
    labels = []
    for line in lines:
        m = _RATING_LINE_RE.match(line)
        if m and not m.group("item") and m.group("value").lower() in _RATING_SET:
            own.append(m.group("value").capitalize())
        labels += [v.capitalize() for v in _RATING_LABEL_RE.findall(line) if v.lower() in _RATING_SET]
    found = own or labels
    return found[0] if found and len(set(found)) == 1 else None


def parse_rating(text: str, default: str = RATING_REVIEW) -> str:
    rating = extract_rating(text)
    return rating if rating is not None else default


def is_review(signal: str) -> bool:
    return signal == RATING_REVIEW


# Overlay sizing map: 5-tier -> fraction of core_size (veto contract, Day 4).
RATING_SIZE_FRAC = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": 0.5, "Sell": 1.0}
