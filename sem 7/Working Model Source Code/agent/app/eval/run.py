"""Eval runner: sessions (cached by deterministic id — reruns don't re-bill) -> labels ->
cost-adjusted paper PnL -> gate verdicts -> JSON report. Live LLM or mocked (tests patch gateway).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from app import schemas as S
from app.agents import graph as G
from app.api.v1 import _cfg_hash
from app.data.base import ROUNDTRIP_COST
from app.db import sqlite_conn
from app.eval import gates
from app.eval.scenarios import SCENARIOS, HORIZON_DAYS, DECISIVE_RET
from app.eval.scenarios_v5 import SCENARIOS_V5, SET_NAME as V5_SET_NAME
from app.eval.alpha import alpha_return

def _ensure_row(sid: str, instrument: str, as_of: datetime):
    conn = sqlite_conn()
    if not conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
        conn.execute("INSERT INTO sessions(id, instrument, as_of, config_hash, status, decision) VALUES (?,?,?,?,?,?)",
                     (sid, instrument, as_of.isoformat(), _cfg_hash(), "queued", None))
        conn.commit()

def forward_return(instrument: str, as_of: datetime, horizon: int = HORIZON_DAYS) -> float:
    """Ground-truth label input: uses POST-as_of data for scoring only. Never fed to agents.

    Day 1 fix (NEW_PLAN T1.2): auto_adjust=True for split/dividend-adjusted
    total return. auto_adjust=False understated drift across splits and added
    label noise on long windows.
    """
    import yfinance as yf
    from datetime import timedelta
    df = yf.download(instrument, start=(as_of - timedelta(days=5)).date().isoformat(),
                     end=(as_of + timedelta(days=horizon + 30)).date().isoformat(),
                     interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, __import__("pandas").MultiIndex):
        df.columns = [c[0] for c in df.columns]
    closes = df["Close"].dropna()
    posts = closes[closes.index.tz_localize("UTC") > as_of] if closes.index.tz is None else closes[closes.index > as_of]
    if len(posts) < horizon + 1:
        raise RuntimeError(f"insufficient forward data for {instrument} {as_of.date()}")
    return float(posts.iloc[horizon] / posts.iloc[0] - 1)

def label_of(fwd: float) -> str:
    return "long" if fwd >= DECISIVE_RET else ("short" if fwd <= -DECISIVE_RET else "flat")

def run_eval(interval: str = "1d", on_progress=None, scenarios: list | None = None,
             set_name: str = "v1-2023-2024") -> dict:
    scenarios = scenarios if scenarios is not None else SCENARIOS
    results = []
    for i, (instrument, day) in enumerate(scenarios):
        as_of = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        sid = G.new_session_id(instrument, as_of.isoformat(), _cfg_hash())
        _ensure_row(sid, instrument, as_of)
        row = sqlite_conn().execute("SELECT status, decision FROM sessions WHERE id=?", (sid,)).fetchone()
        if row[0] == "done" and row[1]:
            dec = S.FinalDecision(**json.loads(row[1]))  # cached: no re-bill
            resumed = True
        else:
            dec = G.run_session(sid, instrument, as_of, interval)
            resumed = False
        fwd = forward_return(instrument, as_of)
        label = label_of(fwd)
        # Alpha vs the regional benchmark (^NSEI), same holding window. Absolute
        # forward return on a single NSE name is dominated by market beta, so the
        # headline accuracy cannot separate skill from "matched the index". Alpha
        # is report-only / raw (None when unsettled) — gates are untouched.
        try:
            alpha = alpha_return(instrument, as_of, horizon=HORIZON_DAYS)
        except Exception:
            alpha = None
        direction = {"buy": "long", "sell": "short", "hold": "flat"}[dec.action]
        correct = direction == label
        traded = 1 if dec.action != "hold" else 0
        pnl = (direction_sign(dec.action) * dec.size * fwd - traded * dec.size * ROUNDTRIP_COST)
        thesis = (G.thesis_history(instrument) or [{}])[-1]
        results.append({"instrument": instrument, "as_of": day, "session": sid, "resumed": resumed,
                        "fwd_ret": round(fwd, 4), "label": label, "action": dec.action,
                        "size": dec.size, "correct": correct, "pnl": round(pnl, 5),
                        "alpha": None if alpha is None else round(alpha, 4),
                        "thesis_status": thesis.get("status")})
        if on_progress:
            on_progress(i + 1, len(scenarios), instrument, day, dec.action, label, correct, resumed)
    report = summarize(results)
    report["scenario_set"] = set_name
    return report

def direction_sign(action: str) -> int:
    return {"buy": 1, "sell": -1, "hold": 0}[action]

def summarize(results: list[dict]) -> dict:
    dec = [r for r in results if r["label"] in ("long", "short")]
    flat = [r for r in results if r["label"] == "flat"]
    acc = sum(r["correct"] for r in dec) / len(dec) if dec else 0.0
    hold_rate = sum(1 for r in flat if r["action"] == "hold") / len(flat) if flat else 1.0
    trade_rate = sum(1 for r in results if r["action"] != "hold") / len(results)
    ok = [r for r in results if r["correct"]]
    wrong = [r for r in results if not r["correct"]]
    if not results:
        cal: bool | None = None
    elif not wrong:
        cal = True  # nothing misclassified: calibration vacuously holds
    elif not ok:
        cal = False
    else:
        cal = (sum(r["size"] for r in ok) / len(ok) > sum(r["size"] for r in wrong) / len(wrong))
    checks = {
        "n_decisive_ok": len(dec) >= gates.MIN_DECISIVE,
        "accuracy": acc >= gates.ACCURACY_MIN,
        "no_edge_hold": hold_rate >= gates.NO_EDGE_HOLD_MIN,
        "trade_rate_in_bounds": gates.TRADE_RATE_LO <= trade_rate <= gates.TRADE_RATE_HI,
        "calibration_direction": bool(cal) if cal is not None else False,
    }
    verdict = "INCONCLUSIVE" if not checks["n_decisive_ok"] else ("PASS" if all(checks.values()) else "FAIL")
    # Honest anchor: score the agent against trivial constant rules on the SAME
    # scenarios (no tokens, scoring-only data). A PASS whose accuracy does not
    # beat the best constant rule is a market-drift artifact, not skill. See
    # app/eval/baselines.py and scripts/analyze_eval.py.
    from app.eval.baselines import compare
    try:
        baseline = compare({"results": results})
    except Exception as e:  # never let the anchor break a report
        baseline = {"error": f"{type(e).__name__}: {e}"}
    return {"gates_frozen": gates.FROZEN_DATE, "n": len(results), "n_decisive": len(dec),
            "accuracy": round(acc, 3), "no_edge_hold_rate": round(hold_rate, 3),
            "trade_rate": round(trade_rate, 3), "total_pnl": round(sum(r["pnl"] for r in results), 4),
            "checks": checks, "verdict": verdict, "baselines": baseline,
            "alpha": alpha_summary(results), "results": results}


def alpha_summary(results: list[dict]) -> dict:
    """Market-neutral read: mean alpha and the sign-hit rate of the agent's trades.

    ``mean_alpha`` is the average raw-minus-^NSEI return over every row with a
    settled alpha (all rows, traded or held — holding into a flat tape is not
    alpha). ``alpha_hit_rate`` counts only rows the agent TRADED: did its chosen
    side beat the index? This is report-only; the frozen gates never read it.
    """
    settled = [r for r in results if r.get("alpha") is not None]
    traded = [r for r in settled if r.get("action") != "hold"]
    sign = {"buy": 1, "sell": -1}
    hits = sum(1 for r in traded if sign.get(r["action"], 0) * r["alpha"] > 0)
    return {
        "n": len(settled),
        "mean_alpha": round(sum(r["alpha"] for r in settled) / len(settled), 4) if settled else None,
        "n_traded": len(traded),
        "alpha_hit_rate": round(hits / len(traded), 3) if traded else None,
    }
