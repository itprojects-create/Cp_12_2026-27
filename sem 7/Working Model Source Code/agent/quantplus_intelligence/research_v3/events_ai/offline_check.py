"""Offline engineering-check pipeline for events_ai (fixtures only).

This module exists so the W4 test suite and the W4 report runner share ONE
scripted fake-model definition. Everything here is SYNTHETIC: the scripted
answers are fixed engineering fixtures written before any metric was computed,
deliberately imperfect, and are NOT a measurement of real Jev quality.
"""
from __future__ import annotations

import json
from pathlib import Path

from quantplus_intelligence.research_v3.events_ai.adapter import (
    JevConfig, JevProviderAdapter, UsageMeter)
from quantplus_intelligence.research_v3.events_ai.baseline import (
    KeywordEventBaseline)
from quantplus_intelligence.research_v3.events_ai.evaluate import (
    GoldLabel, Prediction, evaluate_goldset)
from quantplus_intelligence.research_v3.events_ai.goldset import load_goldset
from quantplus_intelligence.research_v3.events_ai.rubric import (
    EVENT_TYPE_OPTIONS, MATERIALITY_LEVELS)
from quantplus_intelligence.research_v3.events_ai.store import (
    EventClassificationStore)

# Scripted fake-model behaviour: deliberately imperfect, FIXED, written before
# any metric was computed. Keyed by document_id of the synthetic fixtures.
SCRIPTED_MODEL = {
    "synthetic-001": ("financial_results", 0.90, 0.05, 1),
    "synthetic-002": ("financial_results", 0.80, 0.60, 2),   # confusion: guidance->results
    "synthetic-003": ("guidance_change", 0.85, 0.85, 3),
    "synthetic-004": ("financial_results", 0.75, 0.05, 1),
    "synthetic-005": ("other", 0.75, 0.02, 2),               # confusion: contract->other
    "synthetic-006": ("contract", 0.80, 0.02, 2),
    "synthetic-007": ("capital_action", 0.80, 0.02, 3),
    "synthetic-008": ("capital_action", 0.70, 0.02, 2),
    "synthetic-009": ("capital_action", 0.65, 0.02, 2),
    "synthetic-010": ("governance", 0.85, 0.02, 3),
    "synthetic-011": ("governance", 0.80, 0.02, 2),
    "synthetic-012": ("governance", 0.75, 0.02, 2),
    "synthetic-013": ("governance", 0.70, 0.02, 2),
    "synthetic-014": ("governance", 0.70, 0.02, 3),          # confusion: other->governance
    "synthetic-015": ("other", 0.60, 0.02, 1),
    "synthetic-016": ("none", 0.40, 0.02, 0),                # low confidence -> review
    "synthetic-017": ("none", 0.80, 0.02, 0),
    "synthetic-018": ("none", 0.75, 0.02, 0),
    "synthetic-024": ("guidance_change", 0.80, 0.90, 3),
}
SCRIPTED_DEFAULT = ("financial_results", 0.90, 0.05, 1)


def _scripted(doc_id: str) -> tuple[str, float, float, int]:
    return SCRIPTED_MODEL.get(doc_id, SCRIPTED_DEFAULT)


def _choice_probabilities(option: str, confidence: float) -> dict:
    options = list(EVENT_TYPE_OPTIONS)
    rest = (1.0 - confidence) / (len(options) - 1)
    probs = {o: rest for o in options if o != option}
    probs[option] = confidence
    return probs


def _score_probabilities(level: int, confidence: float) -> dict:
    rest = (1.0 - confidence) / (len(MATERIALITY_LEVELS) - 1)
    probs = {str(i): rest for i in range(len(MATERIALITY_LEVELS)) if i != level}
    probs[str(level)] = confidence
    return probs


def build_systemone_response(doc_id: str, option: str, confidence: float,
                             noul: float, level: int,
                             returned_model: str = "jev-1.14.0") -> bytes:
    """A contract-valid SystemOne response body for the scripted fixture."""
    score_probs = _score_probabilities(level, confidence)
    payload = {
        "model": returned_model,
        "answers": {
            "event_type": {"type": "choice", "choice": option,
                           "confidence": confidence,
                           "probabilities": _choice_probabilities(option, confidence)},
            "explicit_guidance_change": {"type": "noul", "noul": noul},
            "materiality": {"type": "score",
                            "score": sum(int(k) * v for k, v in score_probs.items()),
                            "confidence": confidence,
                            "legend": {str(i): v for i, v in enumerate(MATERIALITY_LEVELS)},
                            "probabilities": score_probs},
        },
        "usage": {"input_tokens": 300, "output_tokens": 40},
    }
    return json.dumps(payload).encode("utf-8")


class ScriptedTransport:
    """Fake SystemOne transport: contract-valid responses keyed by document_id."""

    def __init__(self, statuses: list | None = None, returned_model: str = "jev-1.14.0"):
        self.statuses = list(statuses) if statuses else []
        self.calls: list[dict] = []
        self.returned_model = returned_model

    def post(self, url, headers, body, timeout_s):
        self.calls.append({"url": url, "headers": dict(headers),
                           "body": json.loads(body.decode("utf-8")), "timeout_s": timeout_s})
        doc_id = self.calls[-1]["body"]["state"]["document_id"]
        option, confidence, noul, level = _scripted(doc_id)
        if self.statuses:
            status = self.statuses.pop(0)
            if isinstance(status, Exception):
                raise status
            if status == 200:
                return 200, build_systemone_response(doc_id, option, confidence,
                                                     noul, level, self.returned_model)
            return status, json.dumps({"detail": "synthetic error"}).encode("utf-8")
        return 200, build_systemone_response(doc_id, option, confidence, noul, level,
                                             self.returned_model)


def offline_config() -> JevConfig:
    return JevConfig(enabled=True, provider="fake", model="jev-1.14.0",
                     max_requests_per_day=100, max_spend_usd_per_day=10.0,
                     timeout_s=5.0, base_url_override="")


def run_offline_pipeline(store_path: Path | None = None):
    """Evidence -> adapter (scripted fake) -> store -> (gold, baseline, model) preds.

    Deterministic: same inputs produce identical classification ids and metrics.
    """
    goldset = load_goldset()
    adapter = JevProviderAdapter(offline_config(), transport=ScriptedTransport(),
                                 env={}, meter=UsageMeter())
    store = EventClassificationStore(store_path or Path(":memory:"))
    gold: list[GoldLabel] = []
    baseline_preds: list[Prediction] = []
    model_preds: list[Prediction] = []
    classifications = []
    baseline = KeywordEventBaseline()
    for row in goldset.rows:
        if row.expected_adapter != "classify" or row.binding_problem:
            continue
        classification = adapter.classify(row.evidence)
        store.append(classification)
        classifications.append(classification)
        gold.append(row.label)
        model_preds.append(Prediction(
            event_uid=row.label.event_uid,
            event_type=classification.event_type,
            probabilities=dict(classification.event_type_probabilities),
            guidance_change=classification.explicit_guidance_change,
            materiality=classification.materiality_score,
            status=classification.status,
            status_reason=classification.status_reason,
        ))
        base = baseline.classify_text(row.evidence.excerpt_text)
        baseline_preds.append(Prediction(
            event_uid=row.label.event_uid,
            event_type=base.event_type,
            guidance_change=base.guidance_change,
            materiality=base.materiality,
            abstained=base.abstained,
            status="ABSTAIN" if base.abstained else "VALID",
        ))
    metrics = evaluate_goldset(gold, baseline_preds, model_preds)
    return goldset, store, classifications, metrics
