"""Confirmatory vol-magnitude strategy backtest. ONE RUN. Implements
vol_strategy_spec_20261005T110820Z.md exactly. No parameter adjustment.
"""
from __future__ import annotations
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

import features as F
from data import _download

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_END = "2025-12-01"      # train forecast dates strictly before this
HOLD_START = "2026-02-01"     # holdout forecast dates on/after this
HOLD_END = "2026-09-15"       # labels need 10 bars after; data runs to 2026-10-05
MARGIN = 0.10
COST = 0.0021
MIN_SIGNALS = 20
BOOT = 10_000
SEED = 7


def extended_frame() -> pd.DataFrame:
    key = os.path.join(HERE, "data", "holdout_raw_nsei.csv")
    vkey = os.path.join(HERE, "data", "holdout_raw_vix.csv")
    if os.path.exists(key) and os.path.exists(vkey):
        nsei = pd.read_csv(key, index_col=0, parse_dates=True)
        vix = pd.read_csv(vkey, index_col=0, parse_dates=True)
    else:
        nsei = _download("^NSEI", start="2007-01-01", end="2026-10-06")
        vix = _download("^INDIAVIX", start="2007-01-01", end="2026-10-06")
        nsei.to_csv(key)
        vix.to_csv(vkey)
    out = pd.DataFrame({"Close": nsei["Close"]})
    out["VIX"] = vix["Close"].reindex(out.index)
    return out.dropna(subset=["Close"])


def main() -> None:
    px = extended_frame()
    dates = px.index
    close, vix = px["Close"], px["VIX"]
    print(f"data: {dates.min().date()} -> {dates.max().date()} ({len(dates)} bars)")

    r = F.log_returns(close)
    rv20 = r.rolling(20).std() * math.sqrt(252)
    rv60 = r.rolling(60).std() * math.sqrt(252)

    pos_of = {d.date().isoformat(): k for k, d in enumerate(dates)}
    train_rows = []
    for i in range(0, len(dates), 5):
        t = dates[i]
        if not (t < pd.Timestamp(TRAIN_END)):
            continue
        if pd.isna(rv20.iloc[i]) or pd.isna(vix.iloc[i]):
            continue
        seg = r.iloc[i + 1:i + 11].dropna()
        if len(seg) < 10:
            continue
        f10 = float(seg.std() * math.sqrt(252))
        train_rows.append({"f1": F.vol_percentile_rank(rv20, i), "vix": float(vix.iloc[i]),
                           "C": f10})
    tr = pd.DataFrame(train_rows).dropna()
    assert (pd.to_datetime("2007-01-01") <= dates[0]), "history unexpectedly short"
    Xtr, ytr = tr[["f1", "vix"]].to_numpy(), tr["C"].to_numpy()
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    reg = LinearRegression().fit((Xtr - mu) / sd, ytr)
    print(f"train points={len(tr)} (all forecast < {TRAIN_END}), "
          f"coef={reg.coef_.round(4).tolist()} intercept={reg.intercept_:.4f}")

    sigs = []
    i = 0
    while i < len(dates):
        t = dates[i]
        if pd.Timestamp(HOLD_START) <= t <= pd.Timestamp(HOLD_END):
            if not (pd.isna(rv20.iloc[i]) or pd.isna(vix.iloc[i]) or pd.isna(rv60.iloc[i])):
                seg = r.iloc[i + 1:i + 11].dropna()
                if len(seg) == 10:
                    f = float(reg.predict((np.array([[F.vol_percentile_rank(rv20, i),
                                                      float(vix.iloc[i])]]) - mu) / sd)[0])
                    ref = float(rv60.iloc[i])
                    real = float(seg.std() * math.sqrt(252))
                    if f < ref * (1 - MARGIN):
                        side, pay = "short-vol", (ref - real) / ref - COST
                    elif f > ref * (1 + MARGIN):
                        side, pay = "long-vol", (real - ref) / ref - COST
                    else:
                        side, pay = "flat", 0.0
                    sigs.append({"date": t.date().isoformat(), "side": side,
                                 "forecast": round(f, 4), "ref": round(ref, 4),
                                 "realized": round(real, 4),
                                 "ret": pay if side != "flat" else 0.0,
                                 "regime": F.vix_regime_bucket(vix, i)})
        i += 5
    trades = [s for s in sigs if s["side"] != "flat"]
    print(f"holdout points={len(sigs)} non-flat signals={len(trades)}")
    for s in sigs:
        print(f"  {s['date']} {s['side']:9s} f={s['forecast']:.4f} ref={s['ref']:.4f} "
              f"real={s['realized']:.4f} ret={s['ret']:+.4f} {s['regime']}")

    out: dict = {"n_points": len(sigs), "n_signals": len(trades), "signals": sigs}
    if len(trades) >= MIN_SIGNALS:
        rr = np.array([t["ret"] for t in trades])
        sharpe = float(rr.mean() / rr.std() * math.sqrt(252 / 5)) if rr.std() > 0 else 0.0
        rng = np.random.RandomState(SEED)
        bs = []
        for _ in range(BOOT):
            s = rng.choice(rr, size=len(rr), replace=True)
            bs.append(float(s.mean() / s.std() * math.sqrt(252 / 5)) if s.std() > 0 else 0.0)
        lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
        tot = float(rr.sum())
        shares = sorted([t["ret"] / tot for t in trades], reverse=True) if tot != 0 else [0.0] * len(trades)
        out.update({"total_pnl": round(tot, 4), "mean_ret": round(float(rr.mean()), 5),
                    "sharpe": round(sharpe, 3), "sharpe_ci": [round(lo, 3), round(hi, 3)],
                    "top1_share": round(float(shares[0]), 3),
                    "top2_share": round(float(sum(shares[:2])), 3),
                    "n_long": sum(1 for t in trades if t["side"] == "long-vol"),
                    "n_short": sum(1 for t in trades if t["side"] == "short-vol")})
        print(f"\nPnL={tot:+.4f} Sharpe={sharpe:.3f} CI=[{lo:.3f},{hi:.3f}] "
              f"top1={shares[0]:.1%} top2={sum(shares[:2]):.1%}")
    else:
        print(f"\nINCONCLUSIVE: only {len(trades)} signals (< {MIN_SIGNALS})")
    with open(os.path.join(HERE, "data", "strategy_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
