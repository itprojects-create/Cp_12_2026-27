"""Multi-episode robustness: frozen C_M5 on mechanical 2009-2025 spike episodes. ONE RUN.

Frozen method (before any strategy result was computed):
- Episodes: RV20 > trailing-252d 90th pct (min 252 bars history), merge flags
  within 15 trading days. 23 episodes found; detection output is data, not results.
- Per episode: test window = [first_flag - 20 bars, last_flag + 40 bars];
  points every 5th trading day in window; single LinearRegression fit on
  standardized [F1, VIX-level] using all every-5th-day points with forecast
  date < window_start - 20 (embargo); min 20 train points else UNTESTABLE
  (reported, excluded from pooled aggregate with stated reason).
- Signal rule: IDENTICAL to frozen spec (±10% vs trailing-60d RV, size 1,
  cost 0.0021/signal). Zero per-episode tuning.
- Overlap: a test point in two padded windows is assigned to the EARLIEST
  episode; pooled aggregate counts each unique date once.
- Calm: all non-episode-window points 2009-01->2025-12, expanding monthly-fold
  fits (original walk-forward protocol: fit on points < month_start - 20,
  min 100), same frozen signal rule.
- Feb-Sep 2026 holdout excluded entirely (detection cache ends 2025-12-31).
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

HERE = os.path.dirname(os.path.abspath(__file__))
MARGIN = 0.10
COST = 0.0021
MIN_TRAIN = 20
BOOT = 10_000
SEED = 7
STEP = 5
EMBARGO = 20


def detect_episodes(dates, rv) -> list[tuple[int, int]]:
    thr = rv.shift(1).rolling(252, min_periods=252).quantile(0.90)
    flag = (rv > thr) & thr.notna()
    idx = [i for i, v in enumerate(flag) if bool(v)]
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= 15:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    return [(g[0], g[-1]) for g in groups]


def boot_sharpe_ci(rr: np.ndarray):
    sh = float(rr.mean() / rr.std() * math.sqrt(252 / 5)) if rr.std() > 0 else 0.0
    rng = np.random.RandomState(SEED)
    bs = []
    for _ in range(BOOT):
        s = rng.choice(rr, size=len(rr), replace=True)
        bs.append(float(s.mean() / s.std() * math.sqrt(252 / 5)) if s.std() > 0 else 0.0)
    return sh, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def payoff(f: float, ref: float, real: float) -> tuple[str, float]:
    if f < ref * (1 - MARGIN):
        return "short-vol", (ref - real) / ref - COST
    if f > ref * (1 + MARGIN):
        return "long-vol", (real - ref) / ref - COST
    return "flat", 0.0


def summarize(trades: list[dict]) -> dict:
    rr = np.array([t["ret"] for t in trades])
    sh, lo, hi = boot_sharpe_ci(rr)
    tot = float(rr.sum())
    shares = sorted([t["ret"] / tot for t in trades], reverse=True) if tot != 0 else [0.0] * len(trades)
    return {"n": len(trades), "pnl": round(tot, 4), "sharpe": round(sh, 3),
            "ci": [round(lo, 3), round(hi, 3)], "top1": round(float(shares[0]), 3),
            "top2": round(float(sum(shares[:2])), 3),
            "n_long": sum(1 for t in trades if t["side"] == "long-vol"),
            "n_short": sum(1 for t in trades if t["side"] == "short-vol")}


def main() -> None:
    nsei = pd.read_csv(os.path.join(HERE, "data", "NSEI_1d_full.csv"), index_col=0, parse_dates=True)
    vixf = pd.read_csv(os.path.join(HERE, "data", "INDIAVIX_1d_full.csv"), index_col=0, parse_dates=True)
    dates = nsei.index
    close, vix = nsei["Close"], vixf["Close"].reindex(dates)
    r = F.log_returns(close)
    rv20 = r.rolling(20).std() * math.sqrt(252)
    rv60 = r.rolling(60).std() * math.sqrt(252)

    episodes = detect_episodes(dates, rv20)
    print(f"episodes: {len(episodes)}")
    ep_info = []
    for a, b in episodes:
        ep_info.append({"start": dates[a].date().isoformat(), "end": dates[b].date().isoformat(),
                        "win": [max(0, a - 20), min(len(dates) - 1, b + 40)]})
    for e in ep_info:
        print(f"  {e['start']} -> {e['end']} win_bars={e['win']}")

    def feats(i: int):
        return [F.vol_percentile_rank(rv20, i), float(vix.iloc[i])]

    def point(i: int):
        seg = r.iloc[i + 1:i + 11].dropna()
        if len(seg) < 10 or pd.isna(rv20.iloc[i]) or pd.isna(vix.iloc[i]) or pd.isna(rv60.iloc[i]):
            return None
        return {"date": dates[i].date().isoformat(), "pos": i, "f1v": feats(i),
                "ref": float(rv60.iloc[i]),
                "real": float(seg.std() * math.sqrt(252))}

    # full every-5th-day point pool (for per-episode train sets)
    pool = {}
    for i in range(0, len(dates), STEP):
        p = point(i)
        if p:
            pool[i] = p

    per_ep, assigned = [], {}
    for k, e in enumerate(ep_info):
        w0, w1 = e["win"]
        tr = [(pos, p) for pos, p in pool.items() if pos < w0 - EMBARGO]
        test_pos = [i for i in range(w0, w1 + 1, STEP) if i in pool]
        if len(tr) < MIN_TRAIN:
            per_ep.append({"episode": f"{e['start']}->{e['end']}", "status": "UNTESTABLE",
                           "reason": f"only {len(tr)} train points (< {MIN_TRAIN})",
                           "n_test_points": len(test_pos)})
            continue
        Xtr = np.array([p["f1v"] for _, p in tr])
        # labels = fwd10 realized vol (recompute: same as original Target C)
        ytr = np.array([fwd10(close, r, pos) for pos, _ in tr])
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        reg = LinearRegression().fit((Xtr - mu) / sd, ytr)
        trades = []
        for i in test_pos:
            if i in assigned:
                continue
            p = pool[i]
            f = float(reg.predict((np.array([p["f1v"]]) - mu) / sd)[0])
            side, pay = payoff(f, p["ref"], p["real"])
            if side != "flat":
                assigned[i] = k
                trades.append({"date": p["date"], "side": side, "ret": pay,
                               "forecast": round(f, 4), "ref": round(p["ref"], 4),
                               "realized": round(p["real"], 4)})
        s = summarize(trades) if trades else {"n": 0}
        s.update({"episode": f"{e['start']}->{e['end']}", "status": "tested",
                  "n_train": len(tr), "trades": trades})
        per_ep.append(s)
        print(f"{e['start']}->{e['end']}: train={len(tr)} signals={s['n']} "
              f"{('sharpe=%.2f CI=%s pnl=%+.3f top1=%.0f%%' % (s['sharpe'], s['ci'], s['pnl'], s['top1']*100)) if trades else 'NO SIGNALS'}")

    # pooled unique episode signals
    all_ep = [t for e in per_ep if e["status"] == "tested" for t in e["trades"]]
    pooled = summarize(all_ep)
    print(f"\nPOOLED episodes: n={pooled['n']} pnl={pooled['pnl']:+.3f} "
          f"sharpe={pooled['sharpe']:.3f} CI={pooled['ci']} top1={pooled['top1']:.0%} top2={pooled['top2']:.0%}")

    # calm: non-episode points, expanding monthly folds (original protocol)
    win_sets = [set(range(e["win"][0], e["win"][1] + 1)) for e in ep_info]
    in_ep = set().union(*win_sets) if win_sets else set()
    calm_pts = {pos: p for pos, p in pool.items()
                if pos not in in_ep and dates[pos] >= pd.Timestamp("2009-01-01")}
    months = sorted({dates[pos].strftime("%Y-%m") for pos in calm_pts})
    calm_trades = []
    for m in months:
        mpos = [pos for pos in calm_pts if dates[pos].strftime("%Y-%m") == m]
        if not mpos:
            continue
        t0 = min(mpos)
        tr = {pos: p for pos, p in calm_pts.items() if pos < t0 - EMBARGO}
        if len(tr) < 100:
            continue
        Xtr = np.array([p["f1v"] for p in tr.values()])
        ytr = np.array([fwd10(close, r, pos) for pos in tr])
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        reg = LinearRegression().fit((Xtr - mu) / sd, ytr)
        for pos in sorted(mpos):
            p = calm_pts[pos]
            f = float(reg.predict((np.array([p["f1v"]]) - mu) / sd)[0])
            side, pay = payoff(f, p["ref"], p["real"])
            if side != "flat":
                calm_trades.append({"date": p["date"], "side": side, "ret": pay})
    calm = summarize(calm_trades)
    print(f"CALM: n={calm['n']} pnl={calm['pnl']:+.3f} sharpe={calm['sharpe']:.3f} "
          f"CI={calm['ci']} top1={calm['top1']:.0%} top2={calm['top2']:.0%}")

    with open(os.path.join(HERE, "data", "robustness_results.json"), "w", encoding="utf-8") as fh:
        json.dump({"episodes": per_ep, "pooled_episodes": pooled, "calm": calm,
                   "calm_trades": calm_trades}, fh, indent=2)


def fwd10(close: pd.Series, r: pd.Series, i: int) -> float:
    import math as _m
    seg = r.iloc[i + 1:i + 11].dropna()
    assert len(seg) == 10
    return float(seg.std() * _m.sqrt(252))


if __name__ == "__main__":
    main()
