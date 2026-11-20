"""Fingerprint helpers for research memory: exact + near-duplicate detection."""
from __future__ import annotations

import re

from app.research.fingerprints import (  # noqa: F401  (canonical re-export)
    canonical,
    data_fingerprint,
    experiment_fingerprint,
    fp,
    hypothesis_fingerprint,
    parameter_fingerprint,
    strategy_logic_fingerprint,
)

_STOP = frozenset("the a an and or of to in on for with by as at is are was were be may can from".split())


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return frozenset(w for w in words if w not in _STOP and len(w) > 2)


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of content tokens. 1.0 = identical wording."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def idea_text(hypo: dict) -> str:
    return " ".join(str(hypo.get(k, "")) for k in
                    ("title", "thesis", "claimed_mechanism", "strategy_family"))


def near_duplicate(candidate: dict, existing: list[dict],
                   threshold: float = 0.55) -> dict | None:
    """Return the most similar existing hypothesis at/above threshold, else None.
    Exact fingerprint matches are handled by the store before this is consulted."""
    best, best_s = None, 0.0
    cand_text = idea_text(candidate)
    for e in existing:
        s = similarity(cand_text, idea_text(e))
        if s > best_s:
            best, best_s = e, s
    if best is not None and best_s >= threshold:
        return {"match": best, "similarity": round(best_s, 3)}
    return None
