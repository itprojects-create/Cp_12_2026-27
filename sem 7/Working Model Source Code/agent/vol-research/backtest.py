"""Walk-forward volatility backtest (pre-registered configs only; see vol_targets_spec.md).

Protocol: monthly folds from 2009-04, train = strictly-before + 20-bar embargo,
forecast dates every 5th trading day. Thresholds/scalers/models fit on train
only. Persistence baseline computed per point. Bootstrap 95% CI on pooled
(model - baseline) difference, seed fixed.
"""
from __future__ import annotations
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression

import features as F
from data import load_aligned
from targets import binary_label, fwd_realized_vol

HERE = os.path.dirname(os.path.abspath(__file__))
FOLD_START = "2009-04-01"
STEP = 5
EMBARGO_BARS = 20
MIN_TRAIN_POINTS = 100
BOOT = 10_000
SEED = 7


def build_frame() -> pd.DataFrame:
    px = load_aligned()
    close = px["Close"]
    vix = px["VIX"]
    rv = F.realized_vol20(close)
    med = F.trailing_median252(rv)
    ret5 = close.pct_change(5) * 100.0
    abs5 = ret5.abs()
    # vectorized exhaustion threshold, strictly-prior semantics:
    # quantile over bars strictly before i -> rolling().quantile().shift(1)
    thr = abs5.rolling(252, min_periods=60).quantile(0.80).shift(1)
    thr = thr.clip(lower=1.0)
    n_hist = abs5.shift(1).rolling(252, min_periods=1).count()
    thr = thr.where(n_hist >= 60, 8.0)
    flush = (ret5 <= -thr) & thr.notna() & ret5.notna()
    blow = (ret5 >= thr) & thr.notna() & ret5.notna()
    freq = (flush | blow).rolling(20, min_periods=1).sum()

    # consistency: vectorized flags must match the loop reference on samples
    rng = np.random.RandomState(SEED)
    idx = sorted(rng.choice(range(300, len(close) - 30), size=25, replace=False))
    for i in idx:
        f0, b0 = F._flag_at(close, int(i))
        assert bool(flush.iloc[i]) == f0 and bool(blow.iloc[i]) == b0, f"flag mismatch at {i}"

    rows = []
    dates = px.index
    start_pos = dates.searchsorted(pd.Timestamp(FOLD_START))
    for k, i in enumerate(range(start_pos, len(dates) - 20, STEP)):
        t = dates[i]
        if pd.isna(rv.iloc[i]) or pd.isna(med.iloc[i]):
            continue
        f1 = F.vol_percentile_rank(rv, i)
        f2l = float(vix.iloc[i]) if not pd.isna(vix.iloc[i]) else float("nan")
        f2s = F.vix_5d_slope(vix, i)
        f4 = int(freq.iloc[i]) if not pd.isna(freq.iloc[i]) else 0
        f10 = fwd_realized_vol(close, i, 10)
        f20 = fwd_realized_vol(close, i, 20)
        if math.isnan(f10) or math.isnan(f20):
            continue
        m = float(med.iloc[i])
        rows.append({"date": t.isoformat(), "pos": i, "f1": f1, "vix": f2l, "vix_slope": f2s,
                     "f4": f4, "rv": float(rv.iloc[i]), "med": m,
                     "regime": F.vix_regime_bucket(vix, i),
                     "A": binary_label(f10, m), "B": binary_label(f20, m), "C": f10})
    return pd.DataFrame(rows)


def months_of(df: pd.DataFrame):
    df = df.copy()
    df["ym"] = df["date"].str.slice(0, 7)
    return df


def boot_ci(diff: np.ndarray, n: int = BOOT, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.RandomState(seed)
    base = float(diff.mean())
    samp = np.array([rng.choice(diff, size=len(diff), replace=True).mean() for _ in range(n)])
    return base, float(np.percentile(samp, 2.5)), float(np.percentile(samp, 97.5))


CONFIGS = {
    # name: (kind, features or threshold-feature)
    "M1_volpct": ("thr", ["f1"]),
    "M2_vixlevel": ("thr", ["vix"]),
    "M3_vixslope": ("thr_sign", ["vix_slope"]),  # sign rule, no train fit beyond orientation check
    "M4_extremefreq": ("thr", ["f4"]),
    "M5_vol_vix": ("logreg", ["f1", "vix"]),
    "M6_vol_extr": ("logreg", ["f1", "f4"]),
    "M7_all": ("logreg", ["f1", "vix", "f4"]),
}


def run() -> dict:
    df = months_of(build_frame())
    print(f"points={len(df)} folds={df['ym'].nunique()} "
          f"range={df['date'].min()}..{df['date'].max()}")
    df["pos_index"] = df["pos"]
    records = []
    for ym, test in df.groupby("ym", sort=True):
        month_start_pos = int(test["pos"].min())
        train = df[df["pos"] < month_start_pos - EMBARGO_BARS]
        if len(train) < MIN_TRAIN_POINTS:
            continue
        for target in ("A", "B"):
            ytr = (train[target] == "ABOVE").to_numpy()
            if ytr.min() == ytr.max():
                continue  # degenerate train fold: skip (no fit possible)
            for name, (kind, feats) in CONFIGS.items():
                sub = test.dropna(subset=feats)
                if len(sub) == 0:
                    continue
                Xtr = train.dropna(subset=feats)[feats].to_numpy()
                ytr2 = (train.dropna(subset=feats)[target] == "ABOVE").to_numpy()
                if len(Xtr) < 20 or ytr2.min() == ytr2.max():
                    continue
                mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
                if kind == "thr":
                    thr = float(np.median(Xtr[:, 0]))
                    pred = (sub[feats].to_numpy()[:, 0] > thr)
                elif kind == "thr_sign":
                    # orientation from train: does ABOVE coincide with positive slope?
                    orient = 1.0 if ytr2[Xtr[:, 0] > 0].mean() >= ytr2[Xtr[:, 0] <= 0].mean() else -1.0
                    pred = ((sub[feats].to_numpy()[:, 0] * orient) > 0)
                else:
                    clf = LogisticRegression(max_iter=2000)
                    clf.fit((Xtr - mu) / sd, ytr2)
                    pred = clf.predict((sub[feats].to_numpy() - mu) / sd).astype(bool)
                pers = (sub["rv"].to_numpy() > sub["med"].to_numpy())
                actual = (sub[target] == "ABOVE").to_numpy()
                for d, p, b, a, rg in zip(sub["date"], pred, pers, actual, sub["regime"]):
                    records.append({"ym": ym, "date": d, "target": target, "config": name,
                                    "model_ok": bool(p == a), "base_ok": bool(b == a),
                                    "regime": rg, "label": "ABOVE" if a else "BELOW"})
        # regression target C
        for name in ("C_M5", "C_M7"):
            feats = ["f1", "vix"] if name == "C_M5" else ["f1", "vix", "f4"]
            sub = test.dropna(subset=feats)
            tr = train.dropna(subset=feats)
            if len(sub) == 0 or len(tr) < 20:
                continue
            Xtr, ytr = tr[feats].to_numpy(), tr["C"].to_numpy()
            mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
            reg = LinearRegression().fit((Xtr - mu) / sd, ytr)
            pm = reg.predict((sub[feats].to_numpy() - mu) / sd)
            pb = sub["rv"].to_numpy()
            for d, a, m_, b_, rg in zip(sub["date"], sub["C"].to_numpy(), pm, pb, sub["regime"]):
                records.append({"ym": ym, "date": d, "target": "C", "config": name,
                                "mae_m": abs(float(a) - float(m_)), "mae_b": abs(float(a) - float(b_)),
                                "pred": float(m_), "actual": float(a), "regime": rg})
    rec = pd.DataFrame(records)
    rec.to_csv(os.path.join(HERE, "data", "point_records.csv"), index=False)

    out: dict = {"n_points": len(df), "n_folds": int(df["ym"].nunique()),
                 "n_records": len(rec), "binary": {}, "regression": {}}
    brec = rec[rec["target"].isin(["A", "B"])]
    for (tgt, cfg), g in brec.groupby(["target", "config"]):
        d = (g["model_ok"].to_numpy().astype(float) - g["base_ok"].to_numpy().astype(float))
        m, lo, hi = boot_ci(d)
        acc_m = float(g["model_ok"].mean())
        acc_b = float(g["base_ok"].mean())
        calm = g[g["regime"] != "STRESSED"]
        stress = g[g["regime"] == "STRESSED"]
        out["binary"].setdefault(tgt, {})[cfg] = {
            "n": int(len(g)), "folds": int(g["ym"].nunique()),
            "acc_model": round(acc_m, 4), "acc_base": round(acc_b, 4),
            "diff": round(m, 4), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4),
            "sig": bool(lo > 0),
            "calm_diff": round(float(calm["model_ok"].mean() - calm["base_ok"].mean()), 4) if len(calm) else None,
            "stress_diff": round(float(stress["model_ok"].mean() - stress["base_ok"].mean()), 4) if len(stress) else None,
            "n_stress": int(len(stress)),
            "base_rate_above": round(float((g["label"] == "ABOVE").mean()), 4),
        }
    crec = rec[rec["target"] == "C"]
    for cfg, g in crec.groupby("config"):
        dm = -(g["mae_m"].to_numpy() - g["mae_b"].to_numpy())  # >0 means model better
        m, lo, hi = boot_ci(dm)
        pr = g[["pred", "actual"]].corr().iloc[0, 1]
        out["regression"][cfg] = {
            "n": int(len(g)), "mae_model": round(float(g["mae_m"].mean()), 4),
            "mae_base": round(float(g["mae_b"].mean()), 4),
            "mae_diff_b_minus_m": round(m, 4), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4),
            "sig": bool(lo > 0), "corr": round(float(pr), 4),
        }
    # per-year accuracy for the headline configs
    out["per_year"] = {}
    for (tgt, cfg), g in brec[brec["config"].isin(["M7_all", "M1_volpct"])].groupby(["target", "config"]):
        tab = {}
        for yr, gy in g.groupby(g["date"].str.slice(0, 4)):
            tab[yr] = {"n": int(len(gy)), "acc_m": round(float(gy["model_ok"].mean()), 3),
                       "acc_b": round(float(gy["base_ok"].mean()), 3)}
        out["per_year"][f"{tgt}/{cfg}"] = tab
    with open(os.path.join(HERE, "data", "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    out = run()
    print("\n== BINARY (pooled acc model vs persistence; diff CI) ==")
    for tgt in ("A", "B"):
        for cfg, s in out["binary"].get(tgt, {}).items():
            print(f"{tgt} {cfg:14s} n={s['n']:4d} acc {s['acc_model']:.3f} vs {s['acc_base']:.3f} "
                  f"diff {s['diff']:+.4f} [{s['ci_lo']:+.4f},{s['ci_hi']:+.4f}] "
                  f"{'SIG' if s['sig'] else 'ns'} calm {s['calm_diff']:+.4f} stress {s['stress_diff']:+.4f}(n={s['n_stress']})")
    print("\n== REGRESSION C ==")
    for cfg, s in out["regression"].items():
        print(f"C {cfg:6s} n={s['n']} MAE {s['mae_model']:.3f} vs {s['mae_base']:.3f} "
              f"diff {s['mae_diff_b_minus_m']:+.4f} [{s['ci_lo']:+.4f},{s['ci_hi']:+.4f}] "
              f"{'SIG' if s['sig'] else 'ns'} corr {s['corr']:+.3f}")
