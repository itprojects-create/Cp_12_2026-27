"""Part A/C gate: Devil v5.1 reachability probe (6 cases, exit 0 iff 6/6 PASS).

5 real cases from v4 eval checkpoints (never re-fabricated):
  KNOWN-CLEAN, must be HEALTHY: ICICIBANK, AXISBANK, ASIANPAINT
  KNOWN-VETOED-BUT-CORRECT (HEALTHY, or WEAKENED only with a real,
  symmetry-checked reason): SBIN, EICHERMOT
6th BROKEN canary (constructed — no real session ever produced one):
  LONG momentum thesis + generic risks + hand-built blowoff signals.
  PASS = BROKEN, or WEAKENED with raw_override_applied=true and the blowoff
  fact named specifically. FAIL = HEALTHY or verdict without signal reference.
"""
from __future__ import annotations
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import schemas as S
from app.agents.manager import build_devil_prompt

gateway = None  # bound in main() per --provider (codecraft default, openrouter fallback)

CASES = [
    ("ICICIBANK.NS", "CLEAN"),
    ("AXISBANK.NS", "CLEAN"),
    ("ASIANPAINT.NS", "CLEAN"),
    ("SBIN.NS", "VETOED-CORRECT"),
    ("EICHERMOT.NS", "VETOED-CORRECT"),
]

def load_case(instrument: str):
    reps = sorted(glob.glob("data/eval_report_*.json"))
    sid = None
    for p in reversed(reps):  # newest report first (v4 official)
        rep = json.load(open(p))
        for r in rep["results"]:
            if r["instrument"] == instrument:
                sid = r["session"]
                break
        if sid:
            break
    if not sid:
        raise RuntimeError(f"no eval session found for {instrument}")
    conn = sqlite3.connect("data/quantplus.db")
    ck = dict(conn.execute("SELECT stage, payload FROM checkpoints WHERE session_id=?", (sid,)).fetchall())
    reports = {k: S.AnalystReport(**v) for k, v in json.loads(ck["analysts"]).items()}
    thesis = S.Thesis(**json.loads(ck["thesis"]))
    rep_list = [reports[k] for k in ("technical", "fundamentals", "news", "macro", "events")]
    # Same deterministic source Technical used (cached yfinance slice) -> identical dict.
    exh = None
    try:
        from app.data.yfinance_provider import YFinanceProvider
        from app.agents.features import exhaustion_features
        asof = next(r["as_of"] for rep in [json.load(open(p)) for p in reversed(reps)]
                    for r in rep["results"] if r["instrument"] == instrument)
        df = YFinanceProvider().ohlcv(instrument,
                                      datetime.fromisoformat(asof).replace(tzinfo=timezone.utc),
                                      "1d", lookback=60)
        d = exhaustion_features(df, len(df) - 1)
        exh = S.RawExhaustionSignals(
            flush_flag=bool(d["flush_flag"]), blowoff_flag=bool(d["blowoff_flag"]),
            ret_5d_pct=float(d["ret_5d_pct"]),
            dist_from_20d_low_pct=float(d["dist_from_20d_low_pct"]),
            dist_from_20d_high_pct=float(d["dist_from_20d_high_pct"]))
    except Exception as e:
        print(f"  (exhaustion unavailable for {instrument}: {type(e).__name__}; testing None path)")
    return thesis, rep_list, exh

def verdict(inst: str, kind: str, ch: S.Challenge) -> bool:
    if kind == "CLEAN":
        return ch.status == S.ThesisStatus.HEALTHY
    if kind == "VETOED-CORRECT":
        return (ch.status == S.ThesisStatus.HEALTHY or
                (ch.status == S.ThesisStatus.WEAKENED and bool(ch.new_evidence_considered)
                 and ch.direction_symmetry_check_passed is True))
    # CANARY
    text = " ".join(ch.new_evidence_considered + ch.reasons).lower()
    names_signal = any(m in text for m in ("blowoff", "ret_5d", "12", "90th", "20-day high"))
    if ch.status == S.ThesisStatus.BROKEN:
        return names_signal
    if ch.status == S.ThesisStatus.WEAKENED:
        return ch.raw_override_applied is True and names_signal
    return False

def canary_inputs():
    thesis = S.Thesis(direction="long", conviction=0.7,
                      key_evidence=["20-day high breakout on strong momentum continuation"],
                      key_risks=["broader market pullback risk"])
    rep = S.AnalystReport(
        agent="technical",
        summary="Price broke to a 20-day high on strong 5-day momentum, volume confirming the move higher.",
        signals=[{"name": "momentum", "value": 1.2, "direction": "bullish"}],
        confidence=0.72,
        evidence=[{"source": "yfinance", "ref": "CANARY 2024-06-10",
                   "available_at": "2024-06-10T00:00:00Z"}])
    exh = S.RawExhaustionSignals(flush_flag=False, blowoff_flag=True, ret_5d_pct=12.0,
                                 dist_from_20d_low_pct=15.0, dist_from_20d_high_pct=0.3)
    return thesis, [rep], exh

def run_one(name: str, kind: str, thesis, rep_list, exh) -> bool:
    system, user = build_devil_prompt(thesis, rep_list, exh)
    raw = gateway.complete_json(role="devils_advocate", session_id=f"probe-{name}",
                                system=system, user=user)
    ch = S.Challenge(**json.loads(raw))
    ok = verdict(name, kind, ch)
    print(f"{name:14s} {kind:14s} {ch.status.value:8s} override={str(ch.raw_override_applied):5s} "
          f"new_ev={len(ch.new_evidence_considered)} {'PASS' if ok else 'FAIL'}")
    print(f"  claim: {ch.core_claim_restated[:150]}")
    print(f"  new_evidence: {[e[:120] for e in ch.new_evidence_considered][:3]}")
    for r in ch.reasons[:2]:
        print(f"  - {r[:180]}")
    return ok

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["codecraft", "openrouter"], default="codecraft",
                    help="codecraft = official Sonnet path; openrouter = fallback while "
                         "CodeCraft origin is down (results NOT comparable to official)")
    args = ap.parse_args()
    global gateway
    if args.provider == "openrouter":
        from app.gateway.openrouter import gateway as gw
        gateway = gw
        print(f"provider=openrouter model={gw.decider_model}")
    else:
        from app.gateway.codecraft import gateway as gw
        gateway = gw
        print("provider=codecraft")
    allpass = True
    for inst, kind in CASES:
        thesis, rep_list, exh = load_case(inst)
        allpass &= run_one(inst, kind, thesis, rep_list, exh)
    thesis, rep_list, exh = canary_inputs()
    allpass &= run_one("CANARY", "BROKEN-CANARY", thesis, rep_list, exh)
    print("PROBE:", "6/6 ALL-PASS" if allpass else "FAIL")
    print("day tokens:", gateway.day_usage)
    return 0 if allpass else 1

if __name__ == "__main__":
    sys.exit(main())
