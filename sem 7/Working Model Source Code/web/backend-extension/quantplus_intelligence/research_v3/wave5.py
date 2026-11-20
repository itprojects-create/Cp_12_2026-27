"""Narrow read-only adapter for Wave 5 research capabilities.

This is intentionally not a FastAPI router and imports no runtime application,
paper-book, risk-policy or broker module.  A reviewed server layer may expose
these methods later under its existing authentication boundary.
"""
from __future__ import annotations

from pathlib import Path

from quantplus_intelligence.research_v3.crisis import run_crisis_replay
from quantplus_intelligence.research_v3.library import StrategyLibrary
from quantplus_intelligence.research_v3.monitor import LivingResearchJournal


class Wave5ReadOnlyAdapter:
    def __init__(
        self,
        *,
        library: StrategyLibrary,
        journal_path: str | Path | None = None,
        event_store=None,
    ):
        self.library = library
        self.journal_path = Path(journal_path) if journal_path else None
        self.event_store = event_store

    def browse_library(self, query: str = "", **filters) -> tuple[dict, ...]:
        return self.library.search(query, **filters)

    def read_strategy_revision(self, revision_id: str) -> dict | None:
        return self.library.get(revision_id)

    def replay_request(self, conn, **request) -> dict:
        """Compute a retrospective result; persist or mutate nothing."""
        return run_crisis_replay(conn, **request).to_payload()

    def research_journal_status(self) -> dict:
        if self.journal_path is None:
            return {"status": "NOT_CONFIGURED", "authority": "RESEARCH_ONLY"}
        status = LivingResearchJournal(self.journal_path).status()
        status["authority"] = "RESEARCH_ONLY"
        return status

    def event_capture_health(self) -> dict:
        if self.event_store is None:
            return {
                "pipeline_status": "NOT_CONFIGURED",
                "actual_captured_versions": 0,
                "authority": "RESEARCH_ONLY",
            }
        status = self.event_store.health()
        status.update(pipeline_status="STORE_ONLY_COLLECTOR_NOT_INVOKED",
                      authority="RESEARCH_ONLY")
        return status
