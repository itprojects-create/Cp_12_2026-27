"""Specialist briefs: corpse-aware context packs for research roles (§4A–E).

Deterministic (zero tokens): retrieve prior evidence, format corpse blocks,
hand the pack to the orchestrator. Specialists never see raw capital plumbing.
"""
from __future__ import annotations

from app.research_memory import retrieval as RET


def specialist_brief(role: str, query: str, top_k: int = 3) -> dict:
    """Build the brief pack: role prompt + memory evidence + corpse blocks."""
    from app.research.roles import build_role_prompt
    hits = RET.retrieve(query, top_k=top_k)
    corpse_blocks = [RET.format_corpse_match({"title": query}, h)
                     for h in hits if h["kind"] == "corpse"]
    block = "\n\n".join(corpse_blocks)
    system, user = build_role_prompt(role, f"Research question: {query}", block)
    return {"role": role, "query": query, "system": system, "user": user,
            "memory_hits": [{k: h[k] for k in ("kind", "fp", "status", "similarity",
                                               "failure_reason")
                             if k in h} for h in hits],
            "n_corpse_blocks": len(corpse_blocks)}
