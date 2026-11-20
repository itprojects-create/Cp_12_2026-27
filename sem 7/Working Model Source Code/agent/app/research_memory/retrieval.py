"""Retrieval: surface prior evidence (incl. corpses) to research agents (§8)."""
from __future__ import annotations

from app.research_memory import fingerprints as RFP
from app.research_memory import store as ST


def retrieve(query_text: str, top_k: int = 3) -> list[dict]:
    """Keyword-overlap retrieval over hypotheses + corpses. Deterministic,
    zero tokens. Returns prior evidence newest-relevant first."""
    ST.init_tables()
    scored: list[tuple[float, dict]] = []
    for h in ST.list_hypotheses():
        s = RFP.similarity(query_text, RFP.idea_text(h["body"]))
        if s > 0:
            scored.append((s, {"kind": "hypothesis", "fp": h["fp"],
                               "hypothesis_id": h["hypothesis_id"],
                               "status": h["status"], "similarity": round(s, 3),
                               "body": h["body"]}))
    for c in ST.list_corpses():
        s = RFP.similarity(query_text, RFP.idea_text(c["body"]))
        if s > 0:
            scored.append((s, {"kind": "corpse", "fp": c["fp"],
                               "failure_reason": c["failure_reason"],
                               "similarity": round(s, 3),
                               "evidence_required": c["evidence_required"],
                               "body": c["body"]}))
    scored.sort(key=lambda t: -t[0])
    return [r for _, r in scored[:top_k]]


def format_corpse_match(idea: dict, corpse: dict) -> str:
    """The MATCHED PRIOR CORPSE block (§8): what failed, what reuse is allowed,
    what new evidence is required."""
    return (
        "MATCHED PRIOR CORPSE\n\n"
        f"Idea:\n{idea.get('title', idea)}\n\n"
        f"Prior fingerprint:\n{corpse.get('fp')}\n\n"
        f"Failure reason:\n{corpse.get('failure_reason')}\n\n"
        f"Permitted reuse:\n{corpse.get('body', {}).get('allowed_reuse', '(none stated)')}\n\n"
        "New evidence required:\n"
        f"{corpse.get('evidence_required')}\n"
    )
