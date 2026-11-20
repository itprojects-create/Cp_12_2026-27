"""W3 orchestration: PIT features -> W1-engine labels -> purged walk-forward
baselines -> day-clustered diagnostics -> challenger -> journal + artifacts.

Windows (W2-compatible, holdout quarantined):
  train span      2015-06-01 .. 2021-12-31
  validation span 2022-01-01 .. 2023-12-31   (walk-forward folds tile this)
  REVEALED_W2_HOLDOUT 2024-06-21 .. 2026-09-17  -> NEVER TOUCHED by W3
  NEW_SEALED_HOLDOUT -> unavailable (anything fresh would have to come from
  post-2026-09-17 data, which is vendor-only or yet to exist): forward
  protocol instead (see wave3_forward_protocol.md).

Decision cadence: weekly (last session of each ISO week) for snapshots and
h5/h20 labels; monthly (last session of each month) for h60 labels.
Portfolio diagnostics (top-quintile spreads, turnover, concentration) are
computed from the SAME admissible label set — no rolling re-fill, no chained
NAV (train/validation is non-contiguous as segments; W2 discipline applies).

Outputs (reports/alpha_v3_1/): wave3_* artifacts per the handoff §7 list.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab import ResearchJournal
from quantplus_intelligence.research_v3.quantlab import (
    FeaturePanel, build_label, fit_predict, make_folds, purge_ok,
    set_session_index)
from quantplus_intelligence.research_v3.quantlab.adapter import (
    challenge_model_run, model_spec_payload, preregister_model_suite,
    register_model_challenge, register_model_run, top_k_candidates)
from quantplus_intelligence.research_v3.quantlab.contracts import (
    ADMISSIBLE, ModelRun, TrainFold)
from quantplus_intelligence.research_v3.quantlab.metrics import (
    brier, day_clustered_rank_ic, group_by_day, mae)
from quantplus_intelligence.research_v3.quantlab.models import (
    FAMILIES, HGB_CONFIG, LOGISTIC_CONFIG, RIDGE_CONFIG)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "alpha_v3_1"
DB = ROOT / "backend-extension" / "data" / "research_v3" / "warehouse.sqlite3"
assert DB.is_file(), f"warehouse missing: {DB}"

TRAIN_START, TRAIN_END = "2015-06-01", "2021-12-31"
VAL_START, VAL_END = "2022-01-01", "2023-12-31"
N_FOLDS = 4
HORIZONS = (5, 20, 60)          # h5 research-only, h20 primary, h60 secondary
CAPITAL_PAISE = 10_000_000      # label notional (capital-sterile diagnostics)

CONFIG_BY_FAMILY = {
    "climatology_binary": {"constant": 0.5},
    "momentum_rank": {"feature": "ret_60"},
    "reversal_rank": {"feature": "-ret_5"},
    "ridge": RIDGE_CONFIG,
    "logistic": LOGISTIC_CONFIG,
    "hgb": HGB_CONFIG,
}

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def _decision_ts(session: str) -> str:
    d = date.fromisoformat(session[:10]) + timedelta(days=1)
    return f"{d.isoformat()}T00:15:00+05:30"


def weekly_sessions(sessions: list[str]) -> list[str]:
    out: dict[tuple[int, int], str] = {}
    for s in sessions:
        if not (TRAIN_START <= s <= VAL_END):
            continue
        d = date.fromisoformat(s[:10])
        out[(d.isocalendar()[0], d.isocalendar()[1])] = s
    return [out[k] for k in sorted(out)]


def monthly_sessions(sessions: list[str]) -> list[str]:
    out: dict[str, str] = {}
    for s in sessions:
        if not (TRAIN_START <= s <= VAL_END):
            continue
        out[s[:7]] = s
    return [out[k] for k in sorted(out)]


def _members(panel: FeaturePanel, session: str) -> tuple[list[str], int]:
    res = W.members_at(panel.conn, "nifty50", session)
    names = [m for m in res.rows if panel.key_for(m)]
    return names, len(res.rows) - len(names)


def main() -> None:
    conn = W.connect(str(DB))
    panel = FeaturePanel(conn, "nifty50")
    set_session_index(panel.sessions)
    log(f"panel built: {len(panel.series)} spell symbols, {len(panel.sessions)} sessions")

    wk = weekly_sessions(panel.sessions)
    mo = monthly_sessions(panel.sessions)
    log(f"decision cadence: weekly={len(wk)} monthly={len(mo)}")

    # --- snapshots (train+validation only; holdout quarantined) ---------------
    snaps: dict[tuple[str, str], object] = {}
    excluded_unknown = 0
    for cadence, sessions in (("weekly", wk), ("monthly", mo)):
        for session in sessions:
            members, unknown = _members(panel, session)
            excluded_unknown += unknown
            dts = _decision_ts(session)
            for name in members:
                snaps[(name, session)] = panel.snapshot(name, dts, name)
    log(f"snapshots: {len(snaps)} "
        f"(universe names without panel bars: {excluded_unknown} disclosed)")

    # --- labels (W1 engine, unchanged) ----------------------------------------
    log("building labels (W1 executable_label engine) ...")
    labels_ic: dict[tuple[str, str, int], object] = {}
    tasks: list[tuple[str, str, int]] = []
    for (name, session) in snaps:
        if session in wk:
            tasks.append((name, session, 5))
            tasks.append((name, session, 20))
        if session in mo:
            tasks.append((name, session, 60))
    done = 0
    for name, session, h in tasks:
        labels_ic[(name, session, h)] = build_label(
            panel, name, _decision_ts(session), h, exit_ref="CLOSE",
            notional_paise=CAPITAL_PAISE)
        done += 1
        if done % 5000 == 0:
            log(f"  labels {done}/{len(tasks)}")
    admissible = sum(1 for l in labels_ic.values() if l.admissibility == ADMISSIBLE)
    blocked = sum(1 for l in labels_ic.values()
                  if l.admissibility == "DATA_BLOCKED_ACTION_WINDOW")
    nolabel = sum(1 for l in labels_ic.values() if l.admissibility == "NO_LABEL")
    log(f"labels: {len(labels_ic)} total; admissible={admissible} "
        f"data_blocked_action={blocked} no_label={nolabel}")

    # label hash (canonical, deterministic)
    label_hash = _hash_labels(labels_ic)

    # --- folds ------------------------------------------------------------------
    folds = make_folds(panel.sessions, TRAIN_START, VAL_START, VAL_END, N_FOLDS)
    log(f"folds: {[f.fold_id for f in folds]} embargo={folds[0].embargo_sessions}")

    # --- model runs ---------------------------------------------------------------
    feature_names = ("ret_20", "ret_60", "prox_252", "vol_20",
                     "trend_consistency_20", "volume_ratio_20", "liquidity_20",
                     "drawdown_60", "overnight_gap", "rel_mom_60")
    feature_hash = _hash_features(snaps, feature_names)
    all_runs: dict[tuple[str, int], list[ModelRun]] = {}
    failures: list[dict] = []
    for h in HORIZONS:
        for family in FAMILIES:
            fold_runs = []
            for fold in folds:
                run, fail = _run_one(family, CONFIG_BY_FAMILY[family], h, fold,
                                     snaps, labels_ic, wk, mo, feature_names,
                                     feature_hash, label_hash)
                if fail:
                    failures.append(fail)
                    break
                fold_runs.append(run)
            if fold_runs:
                all_runs[(family, h)] = fold_runs
            log(f"family={family} h={h}: "
                f"{'failed: ' + failures[-1]['error'] if not fold_runs else f'{len(fold_runs)} folds'}")

    # --- pooled walk-forward validation metrics -----------------------------------
    metrics = {}
    for (family, h), fold_runs in all_runs.items():
        val_preds = [p for run in fold_runs for p in run.predictions]
        label_map = {(name, session): l for (name, session, hh), l in labels_ic.items() if hh == h}
        pred_by_day = group_by_day(val_preds, "pred")
        y_by_day = {}
        for (name, session), l in label_map.items():
            if not l.usable_for_ic:
                continue
            y_by_day.setdefault(session, {})[name] = l.gross_return
        label_by_day = {d: dict(v) for d, v in y_by_day.items()}
        ic = day_clustered_rank_ic(pred_by_day, label_by_day)
        # thin non-overlapping days for the honest t-stat when horizon > 5
        if h > 5 and ic["n_days"]:
            step = {20: 4, 60: 12}[h]
            days = sorted(pred_by_day)
            thinned_days = days[::step]
            ic_thin = day_clustered_rank_ic(
                {d: pred_by_day[d] for d in thinned_days},
                {d: label_by_day[d] for d in thinned_days if d in label_by_day})
        else:
            ic_thin = None
        probs = family in ("climatology_binary", "logistic", "hgb")
        y_bin = {d: {s: int(v > 0) for s, v in v.items()} for d, v in label_by_day.items()}
        b = brier(pred_by_day, y_bin) if probs else None
        m = mae(pred_by_day, label_by_day)
        quint = _quintile_spread(val_preds, label_by_day)
        # comparators
        ew_daily = [sum(v.values()) / len(v) for v in label_by_day.values()
                    if v]
        ew_mean = round(sum(ew_daily) / len(ew_daily), 6) if ew_daily else None
        metrics[f"{family}@h{h}"] = {
            "rank_ic": ic, "rank_ic_thinned_nonoverlap": ic_thin,
            "brier": b, "mae": m,
            "top_quintile_mean_gross": quint["top"],
            "bottom_quintile_mean_gross": quint["bottom"],
            "spread_top_minus_bottom": quint["spread"],
            "equal_weight_day_mean_gross": ew_mean,
            "n_val_predictions": len(val_preds),
            "n_val_days": len(pred_by_day),
            "benchmark_relative": "DATA_BLOCKED_BASIS_MISMATCH (raw fills vs "
                                  "TRI; diagnostic spread disclosed, never cash)",
            "net_absolute": "DATA_BLOCKED (fee schedule effective 2026-03-01; "
                            "train/validation has no net months)",
        }

    # --- challenger ------------------------------------------------------------------
    class _PooledRun:
        """Lightweight run view over POOLED walk-forward predictions (all
        folds) for the challenge battery; identity = the pooled run_id."""

        def __init__(self, run_id: str, family: str, horizon: int,
                     preds: list[dict]):
            self.run_id = run_id
            self.family = family
            self.horizon_sessions = horizon
            self.predictions = preds

    challenges = {}
    pooled_by_key: dict[str, object] = {}
    for (family, h), fold_runs in all_runs.items():
        val_preds = [p for r in fold_runs for p in r.predictions]
        pooled_run_id = ModelRun.compute_run_id(
            family, CONFIG_BY_FAMILY[family], folds[-1], feature_hash,
            label_hash + f"|pooled{len(fold_runs)}", h)
        pooled = _PooledRun(pooled_run_id, family, h, val_preds)
        label_map = {(n, s): l for (n, s, hh), l in labels_ic.items() if hh == h}
        label_by_day = {}
        for (n, s), l in label_map.items():
            if l.usable_for_ic:
                label_by_day.setdefault(s, {})[n] = l.gross_return
        sens = None
        if family == "momentum_rank":
            sens = {}
            for feat in ("ret_20", "ret_60", "ret_120"):
                preds = []
                for (name, session), snap in snaps.items():
                    if session < VAL_START or session > VAL_END:
                        continue
                    v = snap.features.get(feat)
                    if v is not None:
                        preds.append({"session": session, "symbol": name, "pred": v})
                ic = day_clustered_rank_ic(group_by_day(preds, "pred"), label_by_day)
                sens[feat] = ic["mean_ic"]
        elif family == "ridge":
            sens = {}
            for alpha in (0.1, 1.0, 10.0):
                preds = []
                for fold in folds:
                    r, _f = _run_one("ridge", {**RIDGE_CONFIG, "alpha": alpha}, h,
                                     fold, snaps, labels_ic, wk, mo,
                                     feature_names, feature_hash, label_hash)
                    if r:
                        preds += [p for p in r.predictions]
                ic = day_clustered_rank_ic(group_by_day(preds, "pred"), label_by_day)
                sens[f"alpha={alpha}"] = ic["mean_ic"]
        rep = challenge_model_run(pooled, label_by_day, n_permutations=200,
                                  seed=f"wave3.{family}.h{h}",
                                  sensitivity_ics=sens)
        rep["scope"] = (f"pooled walk-forward validation predictions from "
                        f"{len(fold_runs)} folds; train/validation only")
        challenges[f"{family}@h{h}"] = rep
        pooled_by_key[f"{family}@h{h}"] = pooled

    # --- journal + artifacts ------------------------------------------------------------
    jr = ResearchJournal(str(REPORTS / "wave3_research_journal.jsonl"))
    specs = []
    for h in HORIZONS:
        for family in FAMILIES:
            specs.append(model_spec_payload(
                f"wave3.{family}.h{h}", 1, family, h,
                hypothesis=_hypothesis(family, h), config=CONFIG_BY_FAMILY[family],
                negative_control=(family == "climatology_binary")))
    preregister_model_suite(jr, specs)
    for (family, h), fold_runs in all_runs.items():
        for run in fold_runs:
            register_model_run(jr, run)
    for key, rep in challenges.items():
        family, h = key.split("@h")
        pooled = pooled_by_key[key]
        register_model_challenge(jr, pooled, rep)
    chain_ok, chain_why = jr.verify_chain()

    _write_artifacts(REPORTS, snaps, labels_ic, folds, all_runs, failures,
                     metrics, challenges, jr, (chain_ok, chain_why),
                     feature_hash, label_hash)
    log("done")


def _hypothesis(family: str, h: int) -> str:
    base = (f"research-only diagnostic: does {family} rank cross-sectional "
            f"names better than chance over a {h}-session executable horizon "
            f"(next-session-open entry, {h}-session close exit, raw "
            f"unadjusted fills)?")
    if family == "climatology_binary":
        return base + " Control: constant 0.5 direction probability."
    if family == "momentum_rank":
        return base + " Pre-registered rule: rank by ret_60."
    if family == "reversal_rank":
        return base + " Pre-registered rule: rank by -ret_5 (short-term reversal)."
    return base


def _run_one(family, config, h, fold, snaps, labels_ic, wk, mo,
             feature_names, feature_hash, label_hash):
    train_rows, val_rows = [], []
    excl_train = excl_val = 0
    for (name, session), snap in snaps.items():
        in_train = fold.train_sessions[0] <= session < fold.val_sessions[0]
        in_val = fold.val_sessions[0] <= session <= fold.val_sessions[1]
        if not (in_train or in_val):
            continue
        lab = labels_ic.get((name, session, h))
        if lab is None:
            continue               # cadence mismatch: no label built here
        ok = lab.usable_for_ic
        y = lab.gross_return if ok else None
        row = {"session": session, "symbol": name, "snapshot": snap, "y": y}
        if in_train:
            # purge: drop train rows whose label exit reaches into the
            # validation span minus the embargo
            if not ok or not purge_ok(lab.exit_session, fold.val_sessions[0]):
                excl_train += 1
                continue
            train_rows.append(row)
        else:
            val_rows.append(row)
            if not ok:
                excl_val += 1
    if not train_rows or not val_rows:
        return None, {"family": family, "horizon": h, "fold": fold.fold_id,
                      "error": "empty train or validation rows"}
    res = fit_predict(family, train_rows, val_rows, h, config)
    if not res.get("ok"):
        return None, {"family": family, "horizon": h, "fold": fold.fold_id,
                      "error": res.get("error", "fit failed")}
    run_id = ModelRun.compute_run_id(family, config, fold, feature_hash,
                                     label_hash, h)
    run = ModelRun(
        run_id=run_id, family=family, config=config,
        horizon_sessions=h, fold=fold,
        feature_names=tuple(feature_names), feature_hash=feature_hash,
        label_hash=label_hash,
        n_train_rows=len(train_rows), n_train_days=len({r["session"] for r in train_rows}),
        n_val_rows=len(val_rows), n_val_days=len({r["session"] for r in val_rows}),
        n_excluded_rows=excl_train + excl_val + res.get("excluded_val_rows", 0),
        predictions=tuple(res["predictions"]),
        abstentions=(), diagnostics=res.get("diagnostics", {}),
        warnings=())
    return run, None


def _quintile_spread(preds: list[dict], label_by_day: dict) -> dict:
    """Top/bottom-quintile mean admissible-label gross per day, averaged."""
    by_day: dict[str, list[tuple[str, float]]] = {}
    for p in preds:
        y = label_by_day.get(p["session"], {}).get(p["symbol"])
        if y is not None:
            by_day.setdefault(p["session"], []).append((p["symbol"], p["pred"]))
    tops, bottoms = [], []
    for day in sorted(by_day):
        rows = sorted(by_day[day], key=lambda t: t[1], reverse=True)
        n = max(1, len(rows) // 5)
        tops.append(sum(label_by_day[day][s] for s, _p in rows[:n]) / n)
        bottoms.append(sum(label_by_day[day][s] for s, _p in rows[-n:]) / n)
    if not tops:
        return {"top": None, "bottom": None, "spread": None}
    t, b = sum(tops) / len(tops), sum(bottoms) / len(bottoms)
    return {"top": round(t, 6), "bottom": round(b, 6), "spread": round(t - b, 6)}


def _hash_labels(labels_ic) -> str:
    from quantplus_intelligence.research_v3.lab.spec import fingerprint
    core = sorted((sym, session, h,
                   l.admissibility, l.status,
                   None if l.gross_return is None else round(l.gross_return, 12),
                   l.exit_session)
                  for (sym, session, h), l in labels_ic.items())
    return fingerprint({"labels": core})


def _hash_features(snaps, feature_names) -> str:
    from quantplus_intelligence.research_v3.lab.spec import fingerprint
    core = sorted((sym, session,
                   {k: round(snap.features[k], 12) for k in feature_names
                    if k in snap.features})
                  for (sym, session), snap in snaps.items())
    return fingerprint({"features": core})


def _write_artifacts(reports: Path, snaps, labels_ic, folds, all_runs,
                     failures, metrics, challenges, jr, chain,
                     feature_hash, label_hash) -> None:
    now = _utc()
    # 1. contracts
    contracts = {
        "generated_at": now,
        "feature_names": ["ret_5", "ret_20", "ret_60", "ret_120", "prox_252",
                          "vol_20", "trend_consistency_20", "volume_ratio_20",
                          "liquidity_20", "drawdown_60", "overnight_gap",
                          "rel_mom_60"],
        "unavailable_features": {"sector_relative": "no source-verified, "
                                 "as-of historical sector map (DATA_BLOCKED)"},
        "pit_rules": {
            "cutoff": "features read only bars with available_at <= decision "
                      "T00:15 IST next local day (W1/W2 rule)",
            "window_gate": "lookbacks containing archive session-gaps or "
                           "close/prev_close outside [0.65, 1.54] abstain",
            "imputation": "none; abstaining features are named exclusions "
                          "(complete-row models) or explicit NaN (HGB)",
            "entry": "next-session-open after decision (W1 engine)",
            "exit": "h-session close with conservative extension (W1 engine)",
            "horizons": {"5": "research-only", "20": "primary",
                         "60": "secondary"},
            "purge": "train rows whose label exit_session reaches into the "
                     "validation span minus a 10-session embargo are dropped",
            "holdout_quarantine": "2024-06-21..2026-09-17 (REVEALED_W2_HOLDOUT) "
                                  "is refused by the fold builder",
        },
        "label_admissibility": {
            "ADMISSIBLE": "status OK and no action-shaped discontinuity in "
                          "[entry, exit]",
            "DATA_BLOCKED_ACTION_WINDOW": "unverified corporate-action-shaped "
                                          "discontinuity inside the window",
            "NO_LABEL": "no fill / no baseline",
        },
        "label_hash": label_hash, "feature_hash": feature_hash,
    }
    (reports / "wave3_feature_label_contracts.json").write_text(
        json.dumps(contracts, indent=1, sort_keys=True), encoding="utf-8")

    # 2. model comparison
    comparison = {
        "generated_at": now,
        "windows": {"train": [TRAIN_START, TRAIN_END],
                    "validation": [VAL_START, VAL_END],
                    "revealed_w2_holdout_quarantined": ["2024-06-21", "2026-09-17"],
                    "new_sealed_holdout": "NEW_SEALED_HOLDOUT_UNAVAILABLE"},
        "folds": [{"fold_id": f.fold_id, "train": list(f.train_sessions),
                   "val": list(f.val_sessions), "embargo": f.embargo_sessions}
                  for f in folds],
        "snapshots": len(snaps),
        "labels": _label_counts(labels_ic),
        "runs": [{"family": fam, "horizon": h, "fold": r.fold.fold_id,
                  "run_id": r.run_id, "n_train_rows": r.n_train_rows,
                  "n_train_days": r.n_train_days, "n_val_rows": r.n_val_rows,
                  "n_val_days": r.n_val_days,
                  "n_excluded_rows": r.n_excluded_rows,
                  "diagnostics": r.diagnostics}
                 for (fam, h), fold_runs in sorted(all_runs.items())
                 for r in fold_runs],
        "failures": failures,
        "metrics": metrics,
        "challenges": challenges,
        "candidates_sample": _top_candidates(all_runs, labels_ic),
        "verdict_rules": ("permuted-IC below 90th percentile -> REJECTED; "
                          "diagnostics-only -> RESEARCH_DIAGNOSTIC; net "
                          "absolute and benchmark-relative economics typed "
                          "DATA_BLOCKED; nothing promotes to TRADE"),
    }
    (reports / "wave3_model_comparison.json").write_text(
        json.dumps(comparison, indent=1, sort_keys=True, default=str),
        encoding="utf-8")

    # 3. journal snapshot + manifest
    jr_payload = {"generated_at": now, "journal_path": str(jr.path),
                  "chain_valid": chain[0], "chain_reason": chain[1],
                  "events": len(jr._load())}
    (reports / "wave3_journal_status.json").write_text(
        json.dumps(jr_payload, indent=1, sort_keys=True, default=str),
        encoding="utf-8")

    manifest = {
        "generated_at": now,
        "artifacts": {},
        "code_modules": _module_hashes(),
        "notes": ("result/run identity = canonical-JSON sha256 of semantic "
                  "inputs (family/config/fold/feature/label hashes); "
                  "timestamps excluded from identity"),
    }
    for name in ("wave3_feature_label_contracts.json",
                 "wave3_model_comparison.json", "wave3_journal_status.json"):
        p = reports / name
        manifest["artifacts"][name] = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest["feature_hash"] = feature_hash
    manifest["label_hash"] = label_hash
    (reports / "wave3_reproducibility_manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    log(f"artifacts written to {reports}")


def _label_counts(labels_ic) -> dict:
    counts: dict[str, int] = {}
    for l in labels_ic.values():
        counts[l.admissibility] = counts.get(l.admissibility, 0) + 1
    return {"total": len(labels_ic), **counts}


def _top_candidates(all_runs, labels_ic) -> list[dict]:
    out = []
    for (family, h), fold_runs in sorted(all_runs.items()):
        if h != 20 or family not in ("ridge", "momentum_rank"):
            continue
        run = fold_runs[-1]   # candidate SAMPLE scope: final fold (disclosed)
        label_map = {(n, s): l for (n, s, hh), l in labels_ic.items() if hh == h}
        label_by_day = {}
        for (n, s), l in label_map.items():
            if l.usable_for_ic:
                label_by_day.setdefault(s, {})[n] = l.gross_return
        for c in top_k_candidates(run, label_by_day, 10)[:20]:
            out.append({"family": family, "horizon": h,
                        "scope": f"final fold ({run.fold.fold_id})", **c})
    return out


def _module_hashes() -> dict:
    import quantplus_intelligence.research_v3.quantlab as q
    base = Path(q.__file__).parent
    out = {}
    for p in sorted(base.glob("*.py")):
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    out["scripts/wave3_run_quantlab.py"] = hashlib.sha256(
        Path(__file__).resolve().read_bytes()).hexdigest()
    return out


def _utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
