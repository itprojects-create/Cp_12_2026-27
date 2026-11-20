"""Directional classification metrics with decision-date clustered uncertainty."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable


def _safe_div(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _metrics_from_counts(tn: int, fp: int, fn: int, tp: int) -> dict:
    n = tn + fp + fn + tp
    accuracy = _safe_div(tn + tp, n)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, tn + fp)
    precision = _safe_div(tp, tp + fp)
    balanced = (recall + specificity) / 2 if recall is not None and specificity is not None else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall > 0 else None)
    return {
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "accuracy": accuracy, "balanced_accuracy": balanced,
        "precision_up": precision, "recall_up": recall, "f1_up": f1,
        "specificity_down": specificity,
    }


def summarize_directional(rows: list[dict]) -> dict:
    """Summarize all attempted rows; abstentions count against unconditional accuracy.

    Expected row fields: label_state (ADMISSIBLE/ACTION_BLOCKED/NO_LABEL),
    true_class (0/1/None), tie, predicted_class (0/1/None), session.
    """
    n_attempted = len(rows)
    n_action_blocked = sum(r.get("label_state") == "DATA_BLOCKED_ACTION_WINDOW" for r in rows)
    n_no_label = sum(r.get("label_state") == "NO_LABEL" for r in rows)
    n_ties = sum(bool(r.get("tie")) for r in rows)
    eligible = [r for r in rows if r.get("label_state") == "ADMISSIBLE"
                and not r.get("tie") and r.get("true_class") in (0, 1)]
    answered = [r for r in eligible if r.get("predicted_class") in (0, 1)]
    tn = sum(r["true_class"] == 0 and r["predicted_class"] == 0 for r in answered)
    fp = sum(r["true_class"] == 0 and r["predicted_class"] == 1 for r in answered)
    fn = sum(r["true_class"] == 1 and r["predicted_class"] == 0 for r in answered)
    tp = sum(r["true_class"] == 1 and r["predicted_class"] == 1 for r in answered)
    core = _metrics_from_counts(tn, fp, fn, tp)
    correct = tn + tp
    n_eligible = len(eligible)
    n_answered = len(answered)
    up = sum(r["true_class"] == 1 for r in eligible)
    down = n_eligible - up
    core.update({
        "n_attempted": n_attempted,
        "n_eligible_non_tie": n_eligible,
        "n_up": up, "n_down": down, "n_ties": n_ties,
        "n_action_blocked": n_action_blocked, "n_no_label": n_no_label,
        "n_predictions": n_answered,
        "n_abstentions": n_eligible - n_answered,
        "coverage": _safe_div(n_answered, n_eligible),
        "answered_accuracy": core["accuracy"],
        "unconditional_accuracy": _safe_div(correct, n_eligible),
        "decision_sessions": len({r["session"] for r in eligible}),
    })
    return core


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def clustered_accuracy_interval(rows: list[dict], *, block_sessions: int,
                                n_bootstrap: int, seed: int,
                                accuracy_kind: str = "answered") -> dict:
    """Moving decision-session block bootstrap; stocks are never independent draws."""
    eligible = [r for r in rows if r.get("label_state") == "ADMISSIBLE"
                and not r.get("tie") and r.get("true_class") in (0, 1)]
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {"eligible": 0, "answered": 0, "correct": 0})
    for row in eligible:
        counts = by_day[row["session"]]
        counts["eligible"] += 1
        if row.get("predicted_class") in (0, 1):
            counts["answered"] += 1
            counts["correct"] += int(row["predicted_class"] == row["true_class"])
    days = sorted(by_day)
    if not days:
        return {"method": "moving_decision_session_block_bootstrap",
                "lower_95": None, "upper_95": None, "n_bootstrap": 0,
                "decision_sessions": 0, "block_sessions": block_sessions,
                "effective_nonoverlap_periods": 0}
    block = max(1, min(block_sessions, len(days)))
    starts = list(range(0, max(1, len(days) - block + 1)))
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(n_bootstrap):
        eligible_n = answered_n = correct_n = 0
        sampled_days = 0
        while sampled_days < len(days):
            start = rng.choice(starts)
            selected = days[start:start + block]
            for day in selected:
                counts = by_day[day]
                eligible_n += counts["eligible"]
                answered_n += counts["answered"]
                correct_n += counts["correct"]
            sampled_days += len(selected)
        denominator = answered_n if accuracy_kind == "answered" else eligible_n
        value = _safe_div(correct_n, denominator)
        if value is not None:
            estimates.append(value)
    return {
        "method": "moving_decision_session_block_bootstrap",
        "accuracy_kind": accuracy_kind,
        "lower_95": _percentile(estimates, 0.025),
        "upper_95": _percentile(estimates, 0.975),
        "n_bootstrap": len(estimates),
        "decision_sessions": len(days),
        "block_sessions": block,
        "effective_nonoverlap_periods": len(days) // block,
        "note": "decision sessions are resampled in contiguous blocks; names within a session remain grouped",
    }


def paired_accuracy_difference_interval(model_rows: list[dict], baseline_rows: list[dict], *,
                                        block_sessions: int, n_bootstrap: int,
                                        seed: int) -> dict:
    """Paired block interval for answered accuracy difference on identical keys."""
    key = lambda r: (r["fold_id"], r["session"], r["symbol"])
    m = {key(r): r for r in model_rows if r.get("predicted_class") in (0, 1)}
    b = {key(r): r for r in baseline_rows if r.get("predicted_class") in (0, 1)}
    keys = sorted(set(m) & set(b))
    paired = []
    for item in keys:
        mr, br = m[item], b[item]
        if mr.get("true_class") not in (0, 1) or mr.get("tie") or \
                mr.get("label_state") != "ADMISSIBLE":
            continue
        paired.append({"session": mr["session"],
                       "model_correct": int(mr["predicted_class"] == mr["true_class"]),
                       "baseline_correct": int(br["predicted_class"] == br["true_class"])})
    by_day: dict[str, tuple[int, int]] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in paired:
        grouped[row["session"]].append(row)
    for day, day_rows in grouped.items():
        by_day[day] = (sum(r["model_correct"] - r["baseline_correct"]
                           for r in day_rows), len(day_rows))
    days = sorted(by_day)
    if not days:
        return {"difference": None, "lower_95": None, "upper_95": None,
                "paired_n": 0, "decision_sessions": 0}
    observed = sum(r["model_correct"] - r["baseline_correct"] for r in paired) / len(paired)
    block = max(1, min(block_sessions, len(days)))
    starts = list(range(0, max(1, len(days) - block + 1)))
    rng = random.Random(seed)
    values = []
    for _ in range(n_bootstrap):
        difference_sum = pair_n = 0
        n_days = 0
        while n_days < len(days):
            selected = days[(start := rng.choice(starts)):start + block]
            for day in selected:
                day_sum, day_n = by_day[day]
                difference_sum += day_sum
                pair_n += day_n
            n_days += len(selected)
        values.append(difference_sum / pair_n)
    return {"difference": observed, "lower_95": _percentile(values, 0.025),
            "upper_95": _percentile(values, 0.975), "paired_n": len(paired),
            "decision_sessions": len(days), "block_sessions": block,
            "n_bootstrap": len(values)}


def confidence_coverage_curve(rows: list[dict], thresholds: Iterable[float]) -> list[dict]:
    """Fixed preregistered probability-confidence grid; every point is returned."""
    out = []
    for threshold in thresholds:
        filtered = []
        for row in rows:
            copy = dict(row)
            score = row.get("score")
            if score is None or abs(float(score) - 0.5) < threshold - 0.5:
                copy["predicted_class"] = None
            filtered.append(copy)
        out.append({"probability_threshold": threshold,
                    **summarize_directional(filtered)})
    return out
