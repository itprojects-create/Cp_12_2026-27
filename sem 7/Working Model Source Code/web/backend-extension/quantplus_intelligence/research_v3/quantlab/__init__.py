"""W3 quantitative research subpackage (quantlab): PIT-safe features, labels,
walk-forward folds, modest baseline models, day-clustered diagnostics and W2
lab adapters.

Positioning (blueprint §9): numerical forecasting baselines and controlled
experimental infrastructure — NOT a profitability claim. Real-data economics
stays DATA_BLOCKED on raw unadjusted bars with unverified corporate actions
(exactly as in W2); everything here is RESEARCH_DIAGNOSTIC.

Reuse discipline:
- features extend the W2 `lab.data.PitPanel` (same alias closure, same
  decision-gated bisect, same discontinuity abstention thresholds);
- labels call the W1 `research_v3.labels.executable_label` engine unchanged
  (single source of return truth — no second accounting);
- run identity uses the W2 `lab.spec.fingerprint` canonical-JSON sha256;
- journal events use the W2 `lab.journal.ResearchJournal` schema.

The revealed W2 holdout (2024-06-21..2026-09-17) is quarantined: no W3
training, validation, feature or model-selection computation may touch it.
"""
from __future__ import annotations

from quantplus_intelligence.research_v3.quantlab.contracts import (
    FeatureSnapshot, ModelRun, ReturnLabel, TrainFold)
from quantplus_intelligence.research_v3.quantlab.features import FeaturePanel
from quantplus_intelligence.research_v3.quantlab.folds import (
    REVEALED_W2_HOLDOUT, make_folds, purge_ok, set_session_index)
from quantplus_intelligence.research_v3.quantlab.labeling import build_label, build_labels
from quantplus_intelligence.research_v3.quantlab.metrics import (
    brier, day_clustered_rank_ic, mae)
from quantplus_intelligence.research_v3.quantlab.models import fit_predict

__all__ = [
    "FeatureSnapshot", "ModelRun", "ReturnLabel", "TrainFold",
    "FeaturePanel", "REVEALED_W2_HOLDOUT", "make_folds", "purge_ok",
    "set_session_index", "build_label", "build_labels", "brier",
    "day_clustered_rank_ic", "mae", "fit_predict",
]
