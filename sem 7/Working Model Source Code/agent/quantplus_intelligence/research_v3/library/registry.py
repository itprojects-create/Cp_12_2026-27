"""Pure read-only search adapter over immutable strategy revisions."""
from __future__ import annotations

from dataclasses import replace

from .contracts import StrategyRevision


class StrategyLibrary:
    def __init__(self, revisions: tuple[StrategyRevision, ...] | list[StrategyRevision]):
        items = tuple(revisions)
        ids = [item.revision_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate strategy revision identity")
        self._revisions = items

    def list(self) -> tuple[dict, ...]:
        return tuple(item.to_payload() for item in self._revisions)

    def get(self, revision_id: str) -> dict | None:
        item = next((item for item in self._revisions if item.revision_id == revision_id), None)
        return item.to_payload() if item else None

    def get_revision(self, revision_id: str) -> StrategyRevision | None:
        return next((item for item in self._revisions if item.revision_id == revision_id), None)

    def search(
        self,
        query: str = "",
        *,
        lifecycle_state: str | None = None,
        requirement_state: str | None = None,
    ) -> tuple[dict, ...]:
        needle = query.strip().lower()
        out = []
        for item in self._revisions:
            haystack = " ".join((
                item.strategy_id,
                item.template.title,
                item.template.description,
                item.template.falsifiable_thesis,
            )).lower()
            if needle and needle not in haystack:
                continue
            if lifecycle_state and item.lifecycle_state != lifecycle_state:
                continue
            if requirement_state and not any(
                    requirement.observed_state == requirement_state
                    for requirement in item.requirements):
                continue
            out.append(item.to_payload())
        return tuple(out)

    @staticmethod
    def mint_revision(
        prior: StrategyRevision,
        *,
        semantic_version: str,
        normalized_strategy_spec: dict | None = None,
        revision_note: str,
    ) -> StrategyRevision:
        """Return a new immutable revision; the prior object is never mutated."""
        return replace(
            prior,
            semantic_version=semantic_version,
            normalized_strategy_spec=(normalized_strategy_spec
                                      if normalized_strategy_spec is not None
                                      else dict(prior.normalized_strategy_spec)),
            revision_note=revision_note,
        )
