"""Deterministic keyword baseline over the V2 event taxonomy (thin adapter).

REUSE, not reinvention: the classification rules are the V2
``quantplus_intelligence.forecast.events`` keyword engine — imported read-only
(the file is operator-owned; this adapter never edits it). The V2 rule engine
already abstains on ambiguous text; this adapter only:

1. maps a V2 event ``kind`` into the frozen W4 rubric option space,
2. infers guidance direction (V2 ``guidance_raise``/``guidance_cut``) for the
   noul feature,
3. maps V2 kinds onto the 5-level ordinal materiality scale.

Version binding: ``BASELINE_VERSION`` embeds the sha256 of the V2 taxonomy
source module hash at import time so any operator change to the V2 file is
visible in every baseline classification.
"""
from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass

from quantplus_intelligence.forecast import events as v2_events
from quantplus_intelligence.research_v3.events_ai.rubric import EVENT_TYPE_OPTIONS

# V2 kind -> frozen W4 rubric option
_KIND_TO_OPTION = {
    "promoter_buy": "governance",
    "promoter_sell": "governance",
    "insider_buy": "governance",
    "insider_sell": "governance",
    "pledge_create": "governance",
    "pledge_release": "governance",
    "auditor_resign": "governance",
    "bulk_buy": "other",
    "bulk_sell": "other",
    "rating_upgrade": "other",
    "rating_downgrade": "other",
    "results_scheduled": "financial_results",
    "guidance_raise": "guidance_change",
    "guidance_cut": "guidance_change",
    "earnings_surprise": "financial_results",
}

# V2 kind -> materiality level (0..4)
_KIND_TO_MATERIALITY = {
    "pledge_release": 2, "pledge_create": 2,
    "auditor_resign": 3,
    "rating_upgrade": 2, "rating_downgrade": 3,
    "results_scheduled": 1,
    "guidance_raise": 3, "guidance_cut": 3,
    "earnings_surprise": 3,
    "promoter_buy": 2, "promoter_sell": 2,
    "insider_buy": 2, "insider_sell": 2,
    "bulk_buy": 1, "bulk_sell": 1,
}


def _v2_module_sha256() -> str:
    try:
        source = inspect.getsource(v2_events)
    except (OSError, TypeError):
        source = ""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


BASELINE_VERSION = f"events_ai_keyword_baseline/1(v2_source:{_v2_module_sha256()[:16]})"


@dataclass(frozen=True)
class BaselinePrediction:
    event_type: str | None            # None == the V2 engine abstained
    guidance_change: float            # 1.0 raise, 0.0 cut, 0.5 unknown/none
    materiality: int | None
    abstained: bool
    source_version: str = BASELINE_VERSION


class KeywordEventBaseline:
    """Deterministic baseline: same excerpt in, same answer out, always."""

    def classify_text(self, excerpt_text: str) -> BaselinePrediction:
        kind = v2_events.classify(excerpt_text)
        if kind is None:
            # V2 abstention discipline: ambiguous or unsupported -> abstain.
            return BaselinePrediction(
                event_type=None, guidance_change=0.5, materiality=None, abstained=True)
        if kind == "guidance_raise":
            guidance = 1.0
        elif kind == "guidance_cut":
            guidance = 0.0
        else:
            guidance = 0.5
        return BaselinePrediction(
            event_type=_KIND_TO_OPTION[kind],
            guidance_change=guidance,
            materiality=_KIND_TO_MATERIALITY[kind],
            abstained=False)

    def classify_distribution(self, excerpt_text: str) -> dict:
        """Rubric-shaped distribution view of the deterministic prediction."""
        prediction = self.classify_text(excerpt_text)
        if prediction.abstained:
            return {
                "abstained": True,
                "event_type": None,
                "probabilities": {option: 0.0 for option in EVENT_TYPE_OPTIONS},
                "guidance_change": 0.5,
                "materiality": None,
                "source_version": prediction.source_version,
            }
        return {
            "abstained": False,
            "event_type": prediction.event_type,
            "probabilities": {prediction.event_type: 1.0},
            "guidance_change": prediction.guidance_change,
            "materiality": prediction.materiality,
            "source_version": prediction.source_version,
        }
