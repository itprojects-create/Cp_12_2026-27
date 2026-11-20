"""Recreate purged OOF UP/DOWN predictions for a sealed academic spec."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab.spec import fingerprint
from quantplus_intelligence.research_v3.quantlab.contracts import ADMISSIBLE
from quantplus_intelligence.research_v3.quantlab.features import FeaturePanel
from quantplus_intelligence.research_v3.quantlab.folds import make_folds, purge_ok, set_session_index
from quantplus_intelligence.research_v3.quantlab.models import (
    CORE_LINEAR_FEATURES, HGB_CONFIG, LOGISTIC_CONFIG, RIDGE_CONFIG, fit_predict)

from .contracts import EVIDENCE_TIER, semantic_hash, verify_sealed_spec
from .metrics import (
    clustered_accuracy_interval, confidence_coverage_curve,
    paired_accuracy_difference_interval, summarize_directional)

MODELS = (
    "majority_train", "fixed_up", "trend_ret60", "reversal_ret5",
    "ridge", "logistic", "hgb",
)
FITTED = ("ridge", "logistic", "hgb")
CONFIGS = {"ridge": RIDGE_CONFIG, "logistic": LOGISTIC_CONFIG, "hgb": HGB_CONFIG}


@dataclass(frozen=True)
class AcademicOpenLabel:
    symbol: str
    decision_session: str
    horizon_sessions: int
    admissibility: str
    status: str
    entry_session: str | None
    exit_session: str | None
    exit_extended: bool
    gross_return: float | None
    contamination: tuple[dict, ...]
    membership_strict: bool

    @property
    def usable_for_ic(self) -> bool:
        return (self.admissibility == ADMISSIBLE and self.status == "OK"
                and self.gross_return is not None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decision_ts(session: str) -> str:
    day = date.fromisoformat(session) + timedelta(days=1)
    return f"{day.isoformat()}T00:15:00+05:30"


def weekly_sessions(sessions: list[str], start: str, end: str) -> list[str]:
    last: dict[tuple[int, int], str] = {}
    for session in sessions:
        if start <= session <= end:
            value = date.fromisoformat(session)
            iso = value.isocalendar()
            last[(iso.year, iso.week)] = session
    return [last[key] for key in sorted(last)]


def _members(panel: FeaturePanel, session: str) -> list[str]:
    result = W.members_at(panel.conn, "nifty50", session)
    return [name for name in result.rows if panel.key_for(name)]


def build_open_label_fast(panel: FeaturePanel, symbol: str, decision_ts: str,
                          horizon_sessions: int, *, max_wait_sessions: int = 5
                          ) -> AcademicOpenLabel:
    """In-memory equivalent of W1 executable_label(..., exit_ref='OPEN').

    It deliberately omits benchmark and fee queries because neither enters the
    sealed absolute-direction target. Entry/exit session selection, missing-bar
    extension and discontinuity quarantine are identical to the authoritative
    W1/quantlab path and are parity-tested against ``build_label``.
    """
    key = panel.key_for(symbol)
    if key is None:
        return AcademicOpenLabel(symbol, "", horizon_sessions, "NO_LABEL",
                                 "NO_DECISION_BASELINE", None, None, False,
                                 None, (), False)
    rows = panel.series[key]
    visible = panel._bisect_available(key, decision_ts)
    if visible == 0:
        return AcademicOpenLabel(symbol, "", horizon_sessions, "NO_LABEL",
                                 "NO_DECISION_BASELINE", None, None, False,
                                 None, (), False)
    decision_session = rows[visible - 1][0]
    if visible >= len(rows):
        return AcademicOpenLabel(symbol, decision_session, horizon_sessions,
                                 "NO_LABEL", "NO_FILL", None, None, False,
                                 None, (), bool(panel.spell_strict(key, decision_session)))
    entry_session, entry_open = rows[visible][0], rows[visible][1]
    if entry_open <= 0:
        return AcademicOpenLabel(symbol, decision_session, horizon_sessions,
                                 "NO_LABEL", "NO_FILL", entry_session, None,
                                 False, None, (), bool(panel.spell_strict(key, decision_session)))
    global_entry = bisect.bisect_right(panel.sessions, entry_session)
    following = panel.sessions[global_entry:]
    if len(following) < horizon_sessions:
        return AcademicOpenLabel(symbol, decision_session, horizon_sessions,
                                 "NO_LABEL", "NO_FILL", entry_session, None,
                                 False, None, (), bool(panel.spell_strict(key, decision_session)))
    target = following[horizon_sessions - 1]
    exit_session, exit_open, extended = target, None, False
    target_bar = panel.bar_on(key, target)
    if target_bar is not None and target_bar[0] > 0:
        exit_open = target_bar[0]
    else:
        for candidate in following[horizon_sessions:horizon_sessions - 1 + max_wait_sessions]:
            bar = panel.bar_on(key, candidate)
            if bar is not None and bar[0] > 0:
                exit_session, exit_open, extended = candidate, bar[0], True
                break
    if exit_open is None:
        return AcademicOpenLabel(symbol, decision_session, horizon_sessions,
                                 "NO_LABEL", "NO_FILL", entry_session, None,
                                 False, None, (), bool(panel.spell_strict(key, decision_session)))
    contamination = tuple(panel.holding_discontinuities(
        key, entry_session, exit_session))
    admissibility = "DATA_BLOCKED_ACTION_WINDOW" if contamination else ADMISSIBLE
    return AcademicOpenLabel(
        symbol, decision_session, horizon_sessions, admissibility, "OK",
        entry_session, exit_session, extended, exit_open / entry_open - 1,
        contamination, bool(panel.spell_strict(key, decision_session)))


def _label_core(labels: dict) -> list:
    return sorted((symbol, session, horizon, label.admissibility, label.status,
                   label.entry_session, label.exit_session,
                   None if label.gross_return is None else round(label.gross_return, 12),
                   label.exit_extended, label.membership_strict)
                  for (symbol, session, horizon), label in labels.items())


def _snapshot_core(snapshots: dict) -> list:
    return sorted((symbol, session,
                   {name: round(snapshot.features[name], 12)
                    for name in CORE_LINEAR_FEATURES if name in snapshot.features})
                  for (symbol, session), snapshot in snapshots.items())


def _attempt(label, *, fold_id: str, symbol: str, session: str,
             horizon: int) -> dict:
    usable = label.admissibility == ADMISSIBLE and label.status == "OK" \
        and label.gross_return is not None
    tie = bool(usable and label.gross_return == 0.0)
    true_class = (1 if label.gross_return > 0 else 0) if usable and not tie else None
    return {
        "fold_id": fold_id, "session": session, "symbol": symbol,
        "horizon_sessions": horizon, "label_state": label.admissibility,
        "label_status": label.status, "entry_session": label.entry_session,
        "exit_session": label.exit_session, "exit_extended": label.exit_extended,
        "gross_open_to_open_return": label.gross_return,
        "true_class": true_class, "tie": tie,
        "membership_strict": label.membership_strict,
        "contamination_count": len(label.contamination),
    }


def _prediction_class(model: str, score: float, majority_class: int) -> int:
    if model == "fixed_up":
        return 1
    if model == "majority_train":
        return majority_class
    if model in ("logistic", "hgb"):
        return int(score > 0.5)
    return int(score > 0.0)


def training_majority(train_rows: list[dict]) -> tuple[float, int]:
    """Training-only UP prevalence and deterministic majority class."""
    classes = [int(row["y"] > 0) for row in train_rows if row.get("y") is not None]
    if not classes:
        raise ValueError("training majority requires at least one labelled training row")
    prevalence = sum(classes) / len(classes)
    return prevalence, int(prevalence >= 0.5)


def _model_rows(model: str, attempts: list[dict], snapshots: dict,
                prediction_map: dict[tuple[str, str], float],
                majority_class: int, train_prevalence: float,
                run_id: str) -> list[dict]:
    rows = []
    for attempt in attempts:
        key = (attempt["symbol"], attempt["session"])
        score = None
        if model == "fixed_up":
            score = 1.0
        elif model == "majority_train":
            score = train_prevalence
        elif model == "trend_ret60":
            score = snapshots[key].features.get("ret_60")
        elif model == "reversal_ret5":
            value = snapshots[key].features.get("ret_5")
            score = None if value is None else -value
        else:
            score = prediction_map.get(key)
        predicted = None if score is None else _prediction_class(
            model, float(score), majority_class)
        rows.append({**attempt, "model": model, "score": score,
                     "predicted_class": predicted, "run_id": run_id,
                     "evidence_tier": EVIDENCE_TIER})
    return rows


def _breakdowns(rows: list[dict]) -> dict:
    per_fold, per_year = {}, {}
    for fold in sorted({row["fold_id"] for row in rows}):
        per_fold[fold] = summarize_directional([row for row in rows if row["fold_id"] == fold])
    for year in sorted({row["session"][:4] for row in rows}):
        per_year[year] = summarize_directional([row for row in rows if row["session"].startswith(year)])
    return {"per_fold": per_fold, "per_year": per_year,
            "per_sector": {"status": "UNAVAILABLE_NO_VERIFIED_ASOF_SECTOR_MAP"},
            "per_regime": {"status": "NOT_PREREGISTERED_FOR_THIS_SPRINT"}}


def run_evaluation(spec: dict, db_path: str | Path) -> dict:
    ok, reason = verify_sealed_spec(spec)
    if not ok:
        raise ValueError(reason)
    db_path = Path(db_path).resolve()
    if sha256(db_path) != spec["inputs"]["warehouse_sha256"]:
        raise ValueError("warehouse hash differs from sealed evaluation spec")
    conn = sqlite3.connect("file:" + db_path.as_posix() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    panel = FeaturePanel(conn, "nifty50")
    set_session_index(panel.sessions)
    windows = spec["windows"]
    weekly = weekly_sessions(panel.sessions, windows["train_start"], windows["validation_end"])

    snapshots = {}
    unknown_members = 0
    for session in weekly:
        members = _members(panel, session)
        unknown_members += max(0, len(W.members_at(conn, "nifty50", session).rows) - len(members))
        cutoff = _decision_ts(session)
        for symbol in members:
            snapshots[(symbol, session)] = panel.snapshot(symbol, cutoff, symbol)

    labels = {}
    for (symbol, session), _snapshot in snapshots.items():
        for horizon in spec["targets"]["reported_horizons"]:
            labels[(symbol, session, horizon)] = build_open_label_fast(
                panel, symbol, _decision_ts(session), horizon)

    snapshot_hash = fingerprint({"college_open_to_open_snapshots": _snapshot_core(snapshots)})
    label_hash = fingerprint({"college_open_to_open_labels": _label_core(labels),
                              "exit_ref": "OPEN", "ties": "EXCLUDED_COUNTED"})
    folds = make_folds(
        panel.sessions, windows["train_start"], windows["validation_start"],
        windows["validation_end"], spec["folds"]["n_folds"],
        embargo_sessions=spec["folds"]["embargo_sessions"])

    all_rows: list[dict] = []
    run_inventory: list[dict] = []
    for horizon in spec["targets"]["reported_horizons"]:
        for fold in folds:
            train_rows, val_fit_rows, attempts = [], [], []
            excluded_train = 0
            for (symbol, session), snapshot in snapshots.items():
                in_train = fold.train_sessions[0] <= session < fold.val_sessions[0]
                in_val = fold.val_sessions[0] <= session <= fold.val_sessions[1]
                if not (in_train or in_val):
                    continue
                label = labels[(symbol, session, horizon)]
                usable = label.usable_for_ic and label.gross_return != 0.0
                row = {"session": session, "symbol": symbol,
                       "snapshot": snapshot,
                       "y": label.gross_return if usable else None}
                if in_train:
                    if not usable or not purge_ok(
                            label.exit_session, fold.val_sessions[0],
                            spec["folds"]["embargo_sessions"]):
                        excluded_train += 1
                    else:
                        train_rows.append(row)
                else:
                    val_fit_rows.append(row)
                    attempts.append(_attempt(label, fold_id=fold.fold_id,
                                             symbol=symbol, session=session,
                                             horizon=horizon))
            try:
                train_prevalence, majority_class = training_majority(train_rows)
            except ValueError as exc:
                raise RuntimeError(f"{fold.fold_id} h{horizon}: {exc}") from exc

            prediction_maps = {}
            fitted_meta = {}
            for model in FITTED:
                response = fit_predict(model, train_rows, val_fit_rows, horizon, CONFIGS[model])
                if not response.get("ok"):
                    raise RuntimeError(f"{model} {fold.fold_id} h{horizon}: {response.get('error')}")
                prediction_maps[model] = {
                    (row["symbol"], row["session"]): float(row["pred"])
                    for row in response["predictions"]}
                fitted_meta[model] = {
                    "excluded_val_rows": response["excluded_val_rows"],
                    "diagnostics": response["diagnostics"]}

            for model in MODELS:
                config = (CONFIGS.get(model) or
                          {"rule": {"majority_train": "training prevalence >= 0.5",
                                    "fixed_up": "always UP",
                                    "trend_ret60": "ret_60 > 0",
                                    "reversal_ret5": "-ret_5 > 0"}[model]})
                run_id = semantic_hash({
                    "spec_hash": spec["spec_payload_sha256"], "model": model,
                    "config": config, "horizon": horizon,
                    "fold_hash": fold.fold_id_hash,
                    "snapshot_hash": snapshot_hash, "label_hash": label_hash})
                rows = _model_rows(
                    model, attempts, snapshots, prediction_maps.get(model, {}),
                    majority_class, train_prevalence, run_id)
                all_rows.extend(rows)
                run_inventory.append({
                    "model": model, "horizon_sessions": horizon,
                    "fold_id": fold.fold_id, "fold_hash": fold.fold_id_hash,
                    "run_id": run_id, "config": config,
                    "n_train_rows": len(train_rows),
                    "n_train_days": len({row["session"] for row in train_rows}),
                    "n_val_attempts": len(attempts),
                    "n_excluded_train": excluded_train,
                    "train_up_prevalence": train_prevalence,
                    "train_majority_class": majority_class,
                    **fitted_meta.get(model, {}),
                })

    summaries = []
    common_keys_by_horizon = {}
    rows_by_model_horizon = {}
    for horizon in spec["targets"]["reported_horizons"]:
        model_maps = {}
        for model in MODELS:
            rows = [row for row in all_rows if row["horizon_sessions"] == horizon
                    and row["model"] == model]
            rows_by_model_horizon[(model, horizon)] = rows
            model_maps[model] = {(row["fold_id"], row["session"], row["symbol"]): row
                                 for row in rows}
        common = set.intersection(*[
            {key for key, row in mapping.items()
             if row["predicted_class"] in (0, 1)
             and row["label_state"] == "ADMISSIBLE" and not row["tie"]}
            for mapping in model_maps.values()])
        common_keys_by_horizon[horizon] = common
        block = spec["uncertainty"]["block_sessions_by_horizon"][str(horizon)]
        for model in MODELS:
            rows = rows_by_model_horizon[(model, horizon)]
            for scope, scoped in (
                    ("ALL_ELIGIBLE", rows),
                    ("COMMON_MODEL_SAMPLE", [row for row in rows
                                              if (row["fold_id"], row["session"], row["symbol"]) in common])):
                summary = summarize_directional(scoped)
                summary.update({"model": model, "horizon_sessions": horizon,
                                "sample_scope": scope,
                                "evidence_tier": EVIDENCE_TIER,
                                "accuracy_interval": clustered_accuracy_interval(
                                    scoped, block_sessions=block,
                                    n_bootstrap=spec["uncertainty"]["bootstrap_iterations"],
                                    seed=spec["uncertainty"]["seed"] + horizon
                                         + sum(ord(char) for char in model),
                                    accuracy_kind="answered"),
                                "unconditional_accuracy_interval": clustered_accuracy_interval(
                                    scoped, block_sessions=block,
                                    n_bootstrap=spec["uncertainty"]["bootstrap_iterations"],
                                    seed=spec["uncertainty"]["seed"] + 10_000 + horizon
                                         + sum(ord(char) for char in model),
                                    accuracy_kind="unconditional"),
                                "breakdowns": _breakdowns(scoped)})
                summaries.append(summary)

    baseline_names = ("majority_train", "fixed_up", "trend_ret60")
    baseline_comparison = {}
    for horizon in spec["targets"]["reported_horizons"]:
        common_summaries = [s for s in summaries if s["horizon_sessions"] == horizon
                            and s["sample_scope"] == "COMMON_MODEL_SAMPLE"]
        baselines = [s for s in common_summaries if s["model"] in baseline_names]
        best = max(baselines, key=lambda row: row["answered_accuracy"] or -1)
        baseline_comparison[str(horizon)] = {
            "best_baseline": best["model"],
            "best_baseline_accuracy": best["answered_accuracy"],
            "selection_note": "best of the three predeclared baselines, reported conservatively after scoring; not a model-selection claim",
        }
        baseline_rows = rows_by_model_horizon[(best["model"], horizon)]
        majority_rows = rows_by_model_horizon[("majority_train", horizon)]
        common = common_keys_by_horizon[horizon]
        baseline_rows = [r for r in baseline_rows
                         if (r["fold_id"], r["session"], r["symbol"]) in common]
        majority_rows = [r for r in majority_rows
                         if (r["fold_id"], r["session"], r["symbol"]) in common]
        for summary in common_summaries:
            model_rows = [r for r in rows_by_model_horizon[(summary["model"], horizon)]
                          if (r["fold_id"], r["session"], r["symbol"]) in common]
            summary["difference_vs_best_baseline"] = paired_accuracy_difference_interval(
                model_rows, baseline_rows, block_sessions=block,
                n_bootstrap=spec["uncertainty"]["bootstrap_iterations"],
                seed=spec["uncertainty"]["seed"] + 20_000 + horizon)
            summary["difference_vs_majority_baseline"] = paired_accuracy_difference_interval(
                model_rows, majority_rows, block_sessions=block,
                n_bootstrap=spec["uncertainty"]["bootstrap_iterations"],
                seed=spec["uncertainty"]["seed"] + 30_000 + horizon)

    curves = {}
    for horizon in spec["targets"]["reported_horizons"]:
        for model in ("logistic", "hgb"):
            curves[f"{model}@h{horizon}"] = confidence_coverage_curve(
                rows_by_model_horizon[(model, horizon)],
                spec["decision_rules"]["probability_confidence_grid"])

    label_counts = defaultdict(int)
    ties = defaultdict(int)
    extended = defaultdict(int)
    membership = defaultdict(lambda: {"strict": 0, "weak_or_unknown": 0})
    for (_symbol, _session, horizon), label in labels.items():
        label_counts[(horizon, label.admissibility)] += 1
        if label.admissibility == ADMISSIBLE and label.gross_return == 0.0:
            ties[horizon] += 1
        if label.exit_extended:
            extended[horizon] += 1
        membership[horizon]["strict" if label.membership_strict else "weak_or_unknown"] += 1
    conn.close()
    return {
        "evidence_tier": EVIDENCE_TIER,
        "spec_hash": spec["spec_payload_sha256"],
        "warehouse": {"path": str(db_path), "sha256": sha256(db_path),
                      "open_mode": "SQLite mode=ro + query_only=ON"},
        "dataset": {"session_min": panel.sessions[0], "session_max": panel.sessions[-1],
                    "observed_sessions": len(panel.sessions),
                    "weekly_decision_sessions_train_validation": len(weekly),
                    "snapshots": len(snapshots), "unknown_members": unknown_members,
                    "snapshot_hash": snapshot_hash, "open_to_open_label_hash": label_hash,
                    "label_counts": {f"h{horizon}": {
                        state: count for (h, state), count in label_counts.items() if h == horizon}
                        for horizon in spec["targets"]["reported_horizons"]},
                    "ties": {f"h{horizon}": ties[horizon]
                             for horizon in spec["targets"]["reported_horizons"]},
                    "exit_extended": {f"h{horizon}": extended[horizon]
                                      for horizon in spec["targets"]["reported_horizons"]},
                    "membership_provenance": {f"h{horizon}": membership[horizon]
                                              for horizon in spec["targets"]["reported_horizons"]}},
        "folds": [{"fold_id": fold.fold_id, "fold_hash": fold.fold_id_hash,
                   "train": list(fold.train_sessions), "validation": list(fold.val_sessions),
                   "embargo_sessions": fold.embargo_sessions} for fold in folds],
        "run_inventory": run_inventory,
        "summaries": summaries,
        "baseline_comparison": baseline_comparison,
        "confidence_coverage_curves": curves,
        "oof_rows": all_rows,
        "common_sample_counts": {f"h{horizon}": len(keys)
                                 for horizon, keys in common_keys_by_horizon.items()},
        "holdout_status": "NEW_SEALED_HOLDOUT_UNAVAILABLE",
        "authority": "RESEARCH_ONLY_NO_ORDER_AUTHORITY",
        "result_id": semantic_hash({
            "spec_hash": spec["spec_payload_sha256"], "snapshot_hash": snapshot_hash,
            "label_hash": label_hash,
            "run_ids": sorted(item["run_id"] for item in run_inventory)}),
    }
