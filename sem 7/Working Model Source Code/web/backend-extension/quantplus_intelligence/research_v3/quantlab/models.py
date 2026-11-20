"""W3 baseline model suite: economic/statistical controls before complexity.

Ladder (blueprint §9.1, preregistered configs — NO tuning by results):
  climatology_binary      constant 0.5 (when binary outcomes are defined)
  momentum_rank           score = ret_60 (pre-registered rule)
  reversal_rank           score = -ret_5
  ridge                   sklearn Ridge, train-only standardization
  logistic                sklearn LogisticRegression (direction class)
  hgb                     HistGradientBoostingClassifier (NaN-tolerant;
                          included because sklearn is already installed and
                          sample size is adequate; fixed config, no tuning)

Completeness rule: ridge/logistic receive complete rows only (abstaining
features are named exclusions, never zeros); HGB receives None placeholders
it natively tolerates; rank baselines ignore missing features per name.
Seeds are fixed; every candidate (incl. failures) is logged by the caller.
"""
from __future__ import annotations

import numpy as np

CORE_LINEAR_FEATURES = ("ret_20", "ret_60", "prox_252", "vol_20",
                        "trend_consistency_20", "volume_ratio_20",
                        "liquidity_20", "drawdown_60", "overnight_gap",
                        "rel_mom_60")

RIDGE_CONFIG = {"alpha": 1.0, "standardize": "train_only", "seed": 7}
LOGISTIC_CONFIG = {"C": 1.0, "standardize": "train_only", "seed": 7,
                   "class_weight": None, "max_iter": 200}
HGB_CONFIG = {"max_iter": 150, "learning_rate": 0.05, "max_depth": 3,
              "min_samples_leaf": 100, "random_state": 7, "seed": 7}
FAMILIES = ("climatology_binary", "momentum_rank", "reversal_rank",
            "ridge", "logistic", "hgb")


class _SklearnUnavailable(RuntimeError):
    pass


def _standardizer(train_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean/std fitted on TRAIN rows only (validation never touches it)."""
    mu = train_matrix.mean(axis=0)
    sd = train_matrix.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    return mu, sd


def _complete_rows(rows: list[dict], names: tuple[str, ...]):
    keep, drop = [], 0
    for r in rows:
        v = r["snapshot"].vector_nan(list(names))
        if any(x is None for x in v):
            drop += 1
        else:
            keep.append((r, v))
    return keep, drop


def fit_predict(family: str, train_rows: list[dict], val_rows: list[dict],
                horizon: int, config: dict | None = None) -> dict:
    """Fit on train_rows, predict val_rows. Returns predictions + diagnostics.

    Rows: {"snapshot": FeatureSnapshot, "y": float | None} where y is the
    ADMISSIBLE label gross return (None rows are usable by NaN-tolerant
    families only, never by complete-row families). Predictions are scores;
    for probability families they are P(y > 0); for rank families the score
    is the expected relative ranking key. Returns a typed failure dict when
    the family cannot fit (logged, never silent).
    """
    cfg = dict(config or {})
    try:
        if family == "climatology_binary":
            base = 0.5
            return {"ok": True, "family": family, "config": {"constant": base},
                    "predictions": [{"session": r["session"],
                                     "symbol": r["symbol"], "pred": base}
                                    for r in val_rows],
                    "excluded_val_rows": 0, "diagnostics": {}}

        if family == "momentum_rank":
            name = cfg.get("momentum_feature", "ret_60")
            preds, dropped = [], 0
            for r in val_rows:
                v = r["snapshot"].features.get(name)
                if v is None:
                    dropped += 1
                    continue
                preds.append({"session": r["session"], "symbol": r["symbol"],
                              "pred": v})
            return {"ok": True, "family": family, "config": {"feature": name},
                    "predictions": preds, "excluded_val_rows": dropped,
                    "diagnostics": {}}

        if family == "reversal_rank":
            preds, dropped = [], 0
            for r in val_rows:
                v = r["snapshot"].features.get("ret_5")
                if v is None:
                    dropped += 1
                    continue
                preds.append({"session": r["session"], "symbol": r["symbol"],
                              "pred": -v})
            return {"ok": True, "family": family, "config": {"feature": "-ret_5"},
                    "predictions": preds, "excluded_val_rows": dropped,
                    "diagnostics": {}}

        if family in ("ridge", "logistic", "hgb"):
            return _fit_predict_model(family, train_rows, val_rows, cfg)
        return {"ok": False, "family": family, "error": "unknown family"}
    except Exception as exc:                      # logged candidate failure
        return {"ok": False, "family": family,
                "error": f"{type(exc).__name__}: {exc}"}


def _fit_predict_model(family: str, train_rows: list[dict],
                       val_rows: list[dict], cfg: dict) -> dict:
    names = list(CORE_LINEAR_FEATURES)
    tr_keep, tr_drop = _complete_rows(train_rows, names) if family != "hgb" \
        else ([(r, r["snapshot"].vector_nan(names)) for r in train_rows], 0)
    val_keep, val_drop = _complete_rows(val_rows, names) if family != "hgb" \
        else ([(r, r["snapshot"].vector_nan(names)) for r in val_rows], 0)
    if family == "hgb":
        # NaN-tolerant: keep rows, None -> np.nan placeholders
        tr_keep = [(r, [np.nan if x is None else x for x in v])
                   for r, v in tr_keep]
        val_keep = [(r, [np.nan if x is None else x for x in v])
                    for r, v in val_keep]
    y_tr = np.array([r["y"] for r, _v in tr_keep if r["y"] is not None])
    X_tr = np.array([v for r, v in tr_keep if r["y"] is not None], dtype=float)
    if X_tr.shape[0] < 200 or len(set(y_tr.tolist())) < 2:
        return {"ok": False, "family": family,
                "error": f"insufficient training rows ({X_tr.shape[0]}) or "
                         f"degenerate target"}
    seed = cfg.get("seed", 7)

    if family == "ridge":
        from sklearn.linear_model import Ridge
        mu, sd = _standardizer(X_tr)
        # dense cholesky/svd solve is deterministic; no random_state needed
        model = Ridge(alpha=cfg.get("alpha", 1.0))
        model.fit((X_tr - mu) / sd, y_tr)
        train_scores = model.predict((X_tr - mu) / sd)
        diag = {"train_r2": round(float(model.score((X_tr - mu) / sd, y_tr)), 6),
                "coef": dict(zip(names, [round(float(c), 6) for c in model.coef_]))}
    elif family == "logistic":
        from sklearn.linear_model import LogisticRegression
        y_bin = (y_tr > 0).astype(int)
        if len(set(y_bin.tolist())) < 2:
            return {"ok": False, "family": family, "error": "degenerate classes"}
        mu, sd = _standardizer(X_tr)
        model = LogisticRegression(C=cfg.get("C", 1.0),
                                   max_iter=cfg.get("max_iter", 200),
                                   random_state=seed)
        model.fit((X_tr - mu) / sd, y_bin)
        train_scores = model.predict_proba((X_tr - mu) / sd)[:, 1]
        diag = {"train_brier": round(float(
            ((train_scores - y_bin) ** 2).mean()), 6),
            "base_rate_train": round(float(y_bin.mean()), 4)}
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier
        y_bin = (y_tr > 0).astype(int)
        if len(set(y_bin.tolist())) < 2:
            return {"ok": False, "family": family, "error": "degenerate classes"}
        model = HistGradientBoostingClassifier(
            max_iter=cfg.get("max_iter", 150),
            learning_rate=cfg.get("learning_rate", 0.05),
            max_depth=cfg.get("max_depth", 3),
            min_samples_leaf=cfg.get("min_samples_leaf", 100),
            random_state=cfg.get("random_state", 7))
        model.fit(X_tr, y_bin)
        train_scores = model.predict_proba(X_tr)[:, 1]
        diag = {"train_brier": round(float(
            ((train_scores - y_bin) ** 2).mean()), 6),
            "base_rate_train": round(float(y_bin.mean()), 4)}

    if not val_keep:
        return {"ok": False, "family": family,
                "error": "no usable validation rows after exclusions"}
    X_val = np.array([v for _r, v in val_keep], dtype=float)
    if family == "ridge":
        val_scores = model.predict((X_val - mu) / sd)
    else:
        val_scores = model.predict_proba((X_val - mu) / sd if family == "logistic"
                                         else X_val)[:, 1]
    preds = [{"session": r["session"], "symbol": r["symbol"], "pred": float(s)}
             for (r, _v), s in zip(val_keep, val_scores)]
    return {"ok": True, "family": family, "config": cfg,
            "predictions": preds, "excluded_val_rows": val_drop,
            "diagnostics": diag}
