"""Deterministic text normalization for announcements (P1, §13).

Unicode NFKC, whitespace collapse, HTML strip, exchange boilerplate removal,
attachment-reference canonicalization. Pure function — same input bytes always
produce same output bytes (hash stability tested). Semantic content untouched.
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

NORMALIZER_VERSION = "NORM_V1"

_BOILERPLATE = (
    r"this is to inform you that",
    r"pursuant to regulation \d+.*?sebi.*?regulations.*?2015",
    r"for.*?kind information and record",
    r"yours faithfully,?",
    r"for (?:the )?company",
)

_ATTACH = re.compile(r"(attachment|annexure|enclosed?)[\s:]*([a-z0-9_.\- ]{1,80})",
                     re.IGNORECASE)


def normalize_text(raw: str) -> str:
    """Normalize announcement text deterministically."""
    t = unicodedata.normalize("NFKC", raw or "")
    t = html.unescape(t)
    t = re.sub(r"<[^>]{1,200}>", " ", t)  # bounded HTML tag strip
    # Canonical form is case-folded (documented: matching/duplicate detection
    # is case-insensitive by design; original bytes live untouched in raw store).
    t = t.replace("\r\n", "\n").replace("\r", "\n").lower()
    for pat in _BOILERPLATE:
        t = re.sub(pat, " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = _ATTACH.sub(r"\1: <ref>", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n", "\n", t).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
