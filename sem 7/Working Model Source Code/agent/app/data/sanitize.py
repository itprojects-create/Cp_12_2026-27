"""Sanitize untrusted news text before it enters any prompt (prompt-injection defense)."""
from __future__ import annotations
import html
import re

_INJECTION = re.compile(r"(ignore (previous|all) instructions|system prompt|jailbreak|act as |do anything now)",
                        re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")

def sanitize(text: str, limit: int = 800) -> str:
    t = html.unescape(_TAG.sub(" ", text or ""))
    t = re.sub(r"\s+", " ", t).strip()[:limit]
    if _INJECTION.search(t):
        t = "[FLAGGED-UNTRUSTED-CONTENT-REDACTED] " + _INJECTION.sub("[?]", t)
    return t
