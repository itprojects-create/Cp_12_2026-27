"""Goldset metrics: confusion, per-class P/R/F1, guidance error rates,
calibration/reliability, abstention rates and paired same-sample comparison.

All functions take plain dicts/sequences keyed by ``event_uid`` so tests can
drive them with tiny adversarial fixtures. No function ever looks at market
outcomes: classification quality is computed against independent labels only.
Paired comparisons always operate on the INTERSECTION of uids present in both
systems and report coverage separately — unequal samples are never compared
as if paired.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from quantplus_intelligence.research_v3.events_ai.rubric import (
    EVENT_TYPE_OPTIONS, REVIEW_CONFIDENCE_THRESHOLD)

GUIDANCE_DECISION_THRESHOLD = 0.5


@dataclass(frozen=True)
class GoldLabel:
    event_uid: str
    event_type: str
    guidance_change: bool | None       # None == guidance unknown / not applicable
    materiality: int | None
    needs_review: bool = False


@dataclass(frozen=True)
class Prediction:
    event_uid: str
    event_type: str | None
    probabilities: dict[str, float] = field(default_factory=dict)
    guidance_change: float | None = None       # noul probability of YES
    materiality: float | None = None
    status: str = "VALID"
    status_reason: str | None = None
    abstained: bool = False


def _by_uid(items) -> dict:
    return {item.event_uid: item for item in items}


def event_type_confusion(gold: list[GoldLabel], predictions: list[Prediction],
                         options: tuple[str, ...] = tuple(EVENT_TYPE_OPTIONS)) -> dict:
    """Rows = gold label, cols = prediction. Abstentions counted separately."""
    g = _by_uid(gold)
    p = _by_uid(predictions)
    matrix = {row: {col: 0 for col in (*options, "__ABSTAIN__", "__REVIEW__")} for row in (*options, "__ABSTAIN__")}
    paired_uids = sorted(set(g) & set(p))
    for uid in paired_uids:
        row = g[uid]
        pred = p[uid]
        row_key = row.event_type if row.event_type in options else "__ABSTAIN__"
        if pred.abstained or pred.event_type is None:
            col = "__ABSTAIN__"
        elif pred.status == "NEEDS_REVIEW":
            col = "__REVIEW__"
        else:
            col = pred.event_type if pred.event_type in options else "__ABSTAIN__"
        matrix[row_key][col] += 1
    return {
        "labels": [row for row in (*options, "__ABSTAIN__")],
        "columns": [col for col in (*options, "__ABSTAIN__", "__REVIEW__")],
        "matrix": matrix,
        "paired_n": len(paired_uids),
        "gold_only_uids": sorted(set(g) - set(p)),
        "prediction_only_uids": sorted(set(p) - set(g)),
    }


def per_class_prf(confusion: dict) -> dict:
    """Precision/recall/F1 per option + macro-F1 over options with support."""
    matrix = confusion["matrix"]
    out = {}
    for option in confusion["labels"]:
        if option.startswith("__"):
            continue
        tp = matrix[option][option]
        fp = sum(matrix[row][option] for row in matrix if row != option)
        fn = sum(matrix[option][col] for col in matrix[option] if col != option)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision is not None and recall is not None and precision + recall else None)
        out[option] = {"tp": tp, "fp": fp, "fn": fn,
                       "precision": precision, "recall": recall, "f1": f1}
    supported = [v["f1"] for v in out.values() if v["f1"] is not None]
    out["macro_f1"] = sum(supported) / len(supported) if supported else None
    out["n_scored_classes"] = len(supported)
    return out


def guidance_metrics(gold: list[GoldLabel], predictions: list[Prediction],
                     threshold: float = GUIDANCE_DECISION_THRESHOLD) -> dict:
    """Guidance-change yes/no error rates where BOTH sides express a judgment."""
    g = _by_uid(gold)
    p = _by_uid(predictions)
    tp = fp = tn = fn = skipped_no_label = skipped_no_pred = 0
    brier_sum, brier_n = 0.0, 0
    for uid in sorted(set(g) & set(p)):
        gold_value = g[uid].guidance_change
        pred_value = p[uid].guidance_change
        if gold_value is None:
            skipped_no_label += 1
            continue
        if pred_value is None:
            skipped_no_pred += 1
            continue
        predicted_yes = pred_value >= threshold
        if predicted_yes and gold_value:
            tp += 1
        elif predicted_yes and not gold_value:
            fp += 1
        elif not predicted_yes and gold_value:
            fn += 1
        else:
            tn += 1
        brier_sum += (pred_value - (1.0 if gold_value else 0.0)) ** 2
        brier_n += 1
    total = tp + fp + tn + fn
    return {
        "n_scored": total,
        "skipped_gold_unknown": skipped_no_label,
        "skipped_no_prediction": skipped_no_pred,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "false_positive_rate": fp / total if total else None,
        "false_negative_rate": fn / total if total else None,
        "brier": brier_sum / brier_n if brier_n else None,
    }


def reliability_bins(prob_values: list[tuple[float, float]], n_bins: int = 5) -> list[dict]:
    """(probability, outcome) reliability table. Probabilities are the stated
    model confidences; outcomes are 0/1 gold. Small n => descriptive only."""
    bins = [{"bin": i, "lo": i / n_bins, "hi": (i + 1) / n_bins,
             "n": 0, "mean_prob": None, "mean_outcome": None}
            for i in range(n_bins)]
    for prob, outcome in prob_values:
        if not (math.isfinite(prob) and 0.0 <= prob <= 1.0):
            continue
        index = min(n_bins - 1, int(prob * n_bins))
        entry = bins[index]
        entry["n"] += 1
        entry["mean_prob"] = (entry["mean_prob"] or 0.0) + prob
        entry["mean_outcome"] = (entry["mean_outcome"] or 0.0) + float(outcome)
    for entry in bins:
        if entry["n"]:
            entry["mean_prob"] = entry["mean_prob"] / entry["n"]
            entry["mean_outcome"] = entry["mean_outcome"] / entry["n"]
    return bins


def prevalence(gold: list[GoldLabel]) -> dict:
    counts: dict[str, int] = {}
    for label in gold:
        counts[label.event_type] = counts.get(label.event_type, 0) + 1
    total = len(gold)
    return {option: counts.get(option, 0) / total if total else 0.0
            for option in EVENT_TYPE_OPTIONS} | {"n": total}


def status_rates(predictions: list[Prediction]) -> dict:
    counts = {"VALID": 0, "NEEDS_REVIEW": 0, "ABSTAIN": 0, "INVALID": 0, "UNAVAILABLE": 0}
    for pred in predictions:
        counts[pred.status] = counts.get(pred.status, 0) + 1
    total = len(predictions) or 1
    return counts | {"n": len(predictions),
                     "abstain_or_review_rate": (counts["ABSTAIN"] + counts["NEEDS_REVIEW"]) / total}


def paired_comparison(gold: list[GoldLabel], baseline: list[Prediction],
                      model: list[Prediction]) -> dict:
    """Baseline vs model on the INTERSECTION only; coverage reported honestly."""
    g = _by_uid(gold)
    b = _by_uid(baseline)
    m = _by_uid(model)
    common = sorted(set(b) & set(m))
    agree = disagree_baseline_only = disagree_model_only = both_wrong = 0
    correct: list[str] = []
    for uid in common:
        truth = g[uid].event_type if uid in g else None
        b_ok = b[uid].event_type == truth and b[uid].event_type is not None
        m_ok = m[uid].event_type == truth and m[uid].event_type is not None
        if b_ok and m_ok:
            agree += 1
        elif b_ok and not m_ok:
            disagree_baseline_only += 1
            correct.append("baseline")
        elif m_ok and not b_ok:
            disagree_model_only += 1
            correct.append("model")
        else:
            both_wrong += 1
    return {
        "paired_n": len(common),
        "baseline_only_coverage_n": len(set(b) - set(m)),
        "model_only_coverage_n": len(set(m) - set(b)),
        "both_correct": agree,
        "baseline_correct_model_wrong": disagree_baseline_only,
        "model_correct_baseline_wrong": disagree_model_only,
        "both_wrong": both_wrong,
        "correct_side_sequence": correct,
        "paired_accuracy_baseline": (agree + disagree_baseline_only) / len(common) if common else None,
        "paired_accuracy_model": (agree + disagree_model_only) / len(common) if common else None,
        "interpretation_guard": (
            "paired same-sample comparison only; coverage differences are "
            "reported separately and never counted as accuracy"),
    }


def choice_confidence_points(gold: list[GoldLabel], model: list[Prediction]
                             ) -> list[tuple[float, float]]:
    """(stated confidence for the predicted option, 1 if that option is gold)."""
    g = _by_uid(gold)
    points = []
    for pred in model:
        if pred.abstained or pred.event_type is None or pred.status == "UNAVAILABLE":
            continue
        confidence = pred.probabilities.get(pred.event_type)
        if confidence is None:
            continue
        truth = g.get(pred.event_uid)
        points.append((float(confidence),
                       1.0 if truth is not None and truth.event_type == pred.event_type else 0.0))
    return points


def evaluate_goldset(gold: list[GoldLabel], baseline: list[Prediction],
                     model: list[Prediction]) -> dict:
    confusion_model = event_type_confusion(gold, model)
    confusion_baseline = event_type_confusion(gold, baseline)
    return {
        "sample": {
            "n_gold": len(gold),
            "n_baseline_predictions": len(baseline),
            "n_model_predictions": len(model),
            "needs_review_gold": sum(1 for x in gold if x.needs_review),
        },
        "prevalence": prevalence(gold),
        "baseline": {
            "confusion": confusion_baseline,
            "per_class": per_class_prf(confusion_baseline),
            "status_rates": status_rates(baseline),
            "guidance": guidance_metrics(gold, baseline),
        },
        "model": {
            "confusion": confusion_model,
            "per_class": per_class_prf(confusion_model),
            "status_rates": status_rates(model),
            "guidance": guidance_metrics(gold, model),
            "choice_confidence_reliability": reliability_bins(
                choice_confidence_points(gold, model)),
        },
        "paired": paired_comparison(gold, baseline, model),
        "review_threshold": REVIEW_CONFIDENCE_THRESHOLD,
    }
