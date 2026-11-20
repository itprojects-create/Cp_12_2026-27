"""Research Director: deduplicate, prioritize, cost-rank experiments (§4F, §26).

Deterministic prioritization (no LLM): rank by expected-information-gain per
research cost, penalize corpse overlap and duplicate lineage. The opt-in LLM
review (`director_review`) only re-ranks within the deterministic shortlist —
it cannot invent capital actions (output contract enforced).
"""
from __future__ import annotations

from app.research.schema import ExperimentProposal


def prioritize(proposals: list[ExperimentProposal],
               corpse_fps: set[str] | None = None) -> list[ExperimentProposal]:
    """Order by priority (gain/cost), corpse-adjacent last. Pure function."""
    corpse_fps = corpse_fps or set()
    def key(p: ExperimentProposal) -> tuple:
        # corpse-adjacent (parent in corpse set) sorts after clean ideas
        tainted = any(par in corpse_fps for par in
                      getattr(p, "parent_fps", []) or [])
        return (tainted, -p.priority)
    return sorted(proposals, key=key)


def deduplicate(hypotheses: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split (kept, duplicates) by hypothesis fingerprint. Deterministic."""
    from app.research import fingerprints as FP
    seen: set[str] = set()
    kept, dups = [], []
    for h in hypotheses:
        f = FP.hypothesis_fingerprint(h)
        if f in seen:
            dups.append(h)
        else:
            seen.add(f)
            kept.append(h)
    return kept, dups


def build_director_prompt(proposals: list[dict], memory_notes: str = "") -> tuple[str, str]:
    from app.research.roles import build_role_prompt
    import json
    ctx = ("Candidate experiments (pre-ranked deterministically by gain/cost):\n"
           + json.dumps(proposals, indent=1, default=str)[:6000])
    if memory_notes:
        ctx += "\n\nMemory notes:\n" + memory_notes
    return build_role_prompt("director", ctx)


def director_review(proposals: list[ExperimentProposal], session_id: str,
                    memory_notes: str = "") -> list[str]:
    """Opt-in LLM review: returns ordered hypothesis_ids within the shortlist.
    Lazy import keeps the research package import-safe without gateway creds."""
    from app.agents._util import call_json
    from app.research.roles import validate_role_output
    from pydantic import BaseModel
    shortlist = prioritize(proposals)[:8]

    class _Review(BaseModel):
        model_config = {"frozen": True}
        hypotheses: list = []
        rejected_prior_ideas: list = []
        recommended_experiments: list = []
        required_data: list = []
        falsification_plan: list = []
        uncertainties: list = []
        estimated_value: float = 0.0

    system, user = build_director_prompt(
        [p.model_dump(mode="json") for p in shortlist], memory_notes)
    out = call_json("research_director", session_id, system, user, _Review)
    payload = out.model_dump()
    validate_role_output("director", {k: payload.get(k) for k in
                                      ("hypotheses", "rejected_prior_ideas",
                                       "recommended_experiments", "required_data",
                                       "falsification_plan", "uncertainties",
                                       "estimated_value")})
    valid_ids = {p.hypothesis_id for p in shortlist}
    ordered = [h for h in (payload.get("recommended_experiments") or [])
               if h in valid_ids]
    ordered += [p.hypothesis_id for p in shortlist if p.hypothesis_id not in ordered]
    return ordered
