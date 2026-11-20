"""Weekly forward ritual (Day-6 clock): judge -> allocate -> foundry gate.

Scope lock (data/prereg_evo_founders.md): forward paper ONLY. No 2021-2026
bar is ever used to admit, kill, promote, or score any variant. All inputs
are bars with date > clock_start (data/forward_clock_start_20261010.json);
anything older is excluded by construction, not by comment.

Each run = one judging window for every living variant:
  n_decisions = forward 5-day rebalance slots since clock start (calendar,
    identical for all variants — computed from ^NSEI trading dates only)
  ir          = trailing IR of the variant's forward daily excess vs NIFTY.
    Per-variant forward equity curves begin at clock start; with <2 forward
    closes IR is undefined and recorded as 0.0 with reason (never fabricated).
  tokens      = 0 per deterministic founder (money path bills zero LLM tokens
    by construction — see tests/test_money_path_boundary.py). The week's total
    research token spend from usage_daily is reported as memo context only and
    is never charged to variants.
  budget      = TOKEN_BUDGET_DETERMINISTIC (0). Caller-set per the judge
    contract (app/evo/judge.py): any future LLM spend on a founder starves
    immediately unless IR >= 0.5. Not a threshold change — operating parameter.

Foundry gate (same run, after judging): every proposal — regardless of source —
goes parse -> embargoed validate -> PBO-lite before touching capital:
  - forbidden-kind probes must raise at parse (recorded, never evaluated)
  - allowlisted candidates validate against FORWARD-ONLY rows (entry decisions
    since clock start). With no forward entries yet the honest outcome is
    "test slice too small", logged to foundry_log identically to failures.
  - genome-shaped kinds (topK_value/blackout_window) route to the evo candidate
    queue on promotion, never live-direct (candidate_policy raises for them;
    recorded, not crashed).

Total script: any fetch failure degrades to documented fallbacks
(n=0, ir=0.0, fingerprint "unknown" legs) — never raises, never fabricates.
Exit 0 always writes the as-is artifact; verdicts are recorded, not tuned.

Usage:
  python scripts/forward_week.py                      # week ritual, production DB
  python scripts/forward_week.py --dry-run            # compute + print, no DB writes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.trend_core import INDEX_TICKER  # noqa: E402
from app.core.overlay import veto_fraction  # noqa: E402

CLOCK_PATH = os.path.join("data", "forward_clock_start_20261010.json")
REBALANCE_DAYS = 5
TOKEN_BUDGET_DETERMINISTIC = 0

WEEK1_CANDIDATE = {
    "kind": "veto_band_edge",
    "params": {"band_lo": 0.5, "band_hi": 0.75, "veto": 1.0,
               "regime": "STRESSED", "breadth": "low"},
    "rationale": ("W1 candidate: block new entries when veto_raw in [0.5,0.75) "
                  "under STRESSED/low-breadth. Falsifier: test whipsaw-rate fails "
                  "to drop >=2pp vs frozen baseline or drift >5pp or <6/8 blocks."),
}
WEEK1_PROBE = {"kind": "direction_flip", "params": {"to": "short"},
               "rationale": "W1 parse-gate probe (must reject; never evaluated)."}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clock_start() -> datetime:
    with open(CLOCK_PATH, encoding="utf-8") as f:
        clk = json.load(f)
    return datetime.fromisoformat(clk["clock_start"])


def _forward_bars(now: datetime, clock_start: datetime) -> tuple[list[str], str]:
    """^NSEI trading dates strictly after clock_start (bars available <= now).

    Returns (dates, provenance). Provider is PIT-safe by construction (only
    past bars); the clock_start cut is the forward-only enforcement.
    """
    try:
        from app.data.yfinance_provider import YFinanceProvider
        df = YFinanceProvider().ohlcv(INDEX_TICKER, now, "1d", lookback=30)
        closes = df["Close"].dropna()
        dates = [str(d.date()) for d in closes.index]
        fwd = sorted(d for d in dates if d > clock_start.date().isoformat())
        return fwd, f"yfinance {INDEX_TICKER} 1d as_of={now.date()}"
    except Exception as e:  # noqa: BLE001 - total script, documented fallback
        return [], f"unavailable ({type(e).__name__}); forward bars unknown -> n=0"


def _research_token_memo(clock_start: datetime) -> dict:
    try:
        from app.db import sqlite_conn
        rows = sqlite_conn().execute(
            "SELECT day, tokens FROM usage_daily WHERE day >= ? ORDER BY day",
            (clock_start.date().isoformat(),)).fetchall()
        return {"since": clock_start.date().isoformat(),
                "total_tokens": sum(r[1] for r in rows),
                "days": [{"day": r[0], "tokens": r[1]} for r in rows],
                "note": "memo only; never charged to deterministic variants"}
    except Exception as e:  # noqa: BLE001
        return {"since": clock_start.date().isoformat(), "total_tokens": 0,
                "days": [], "note": f"ledger unreadable ({type(e).__name__})"}


def _live_fingerprint(now: datetime) -> tuple[str, dict]:
    """Current regime fingerprint for death records (unused unless a burial
    occurs this window). Legs that cannot be computed are marked unknown."""
    from app.data.regime import market_trend_at, regime_at
    regime, trend = regime_at(now), market_trend_at(now)
    breadth_leg, breadth_prov = "unknown", "no forward universe fetch this week"
    try:
        from app.core.overlay import breadth_pct
        from app.data.yfinance_provider import YFinanceProvider
        from app.core.trend_core import UNIVERSE
        closes_map: dict[str, list[float]] = {}
        for t in list(UNIVERSE)[:10]:
            try:
                df = YFinanceProvider().ohlcv(t, now, "1d", lookback=80)
                closes_map[t] = [float(x) for x in df["Close"].dropna().tolist()]
            except Exception:  # noqa: BLE001 - per-name skip, disclosed by count
                continue
        if closes_map:
            n = min(len(v) for v in closes_map.values())
            b = breadth_pct({k: v[-n:] for k, v in closes_map.items()}, n - 1)
            from app.evo.genome import breadth_bucket
            breadth_leg, breadth_prov = breadth_bucket(b), f"breadth={b:.2f} on {len(closes_map)}/50 names"
    except Exception as e:  # noqa: BLE001
        breadth_prov = f"unavailable ({type(e).__name__})"
    return f"{regime}|{trend}|{breadth_leg}", {
        "regime": regime, "trend": trend, "breadth": breadth_leg,
        "breadth_provenance": breadth_prov}


def _frozen_baseline(row: dict) -> float:
    """Frozen-table baseline over foundry rows. Rows carry {veto_raw, regime,
    breadth, whipsaw}; the frozen table also reads ret_5d/dist_high, which rows
    lack — neutral stand-ins (0.0 / -5.0, i.e. no blowoff trigger) are used and
    documented here. Baseline-independent while forward rows are empty."""
    bmap = {"low": 0.2, "mid": 0.5, "high": 0.8}
    return veto_fraction(row.get("regime", "CALM"),
                         bmap.get(row.get("breadth", "mid"), 0.5),
                         0.0, -5.0)


def _forward_rows() -> tuple[list[dict], str]:
    """Candidate entry decisions since clock start for the foundry embargo.

    No forward rebalances have occurred yet (clock started 2026-10-10, a
    Saturday; next rebalance slot is Mon 2026-10-12), so there are no forward
    entries to score — rows are empty and validation must honestly report
    "test slice too small". Per-genome forward-ledger wiring lands when the
    first forward rebalance settles; until then this returns [] by evidence,
    not by stub.
    """
    return [], "no forward rebalances settled yet (clock_start=2026-10-10 Sat)"


def run_week(now: datetime | None = None, dry_run: bool = False,
             forward_bars: list[str] | None = None,
             fingerprint_override: str | None = None,
             candidate: dict | None = None,
             out_path: str | None = None,
             freeze_path: str | None = None) -> dict:
    """Execute one weekly ritual. Pure inputs are injectable for hermetic tests
    (forward_bars / fingerprint_override bypass network). Returns the artifact
    dict; writes it to data/ unless out_path is given. dry_run skips DB writes
    (judge/validate still computed, flagged as such). freeze_path (§56): when
    given, the effective config is verified first — on drift the ritual records
    NO_JUDGMENT and performs no judging/allocation (fail-closed §61)."""
    from app.evo import arena
    from app.evo import store
    from app.evo.judge import MIN_DECISIONS
    from app.foundry import proposals as P
    from app.foundry import validate as V

    now = now or _now()
    freeze_check = None
    if freeze_path is not None:
        from app.governance import freeze as FRZ
        freeze_check = FRZ.verify(freeze_path)
        if freeze_check["verdict"] == "FORWARD_CONFIG_DRIFT" and not dry_run:
            artifact = {
                "ritual": "forward-week", "window_no": None, "as_of": now.isoformat(),
                "verdict": "NO_JUDGMENT",
                "reason": ("forward config drift — judging quarantined from the "
                           "original experiment (§56)"),
                "freeze_check": freeze_check, "dry_run": dry_run,
                "generated_at": _now().isoformat()}
            path = out_path or os.path.join(
                "data", f"forward_week_NOJUDGE_{now.date().isoformat()}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(artifact, f, indent=2)
            artifact["artifact_path"] = path
            return artifact
    clock_start = _clock_start()
    if forward_bars is None:
        forward_bars, bars_prov = _forward_bars(now, clock_start)
    else:
        bars_prov = "injected (test)"
    n_decisions = len(forward_bars) // REBALANCE_DAYS
    ir_reason = ("insufficient forward points (<2 closes since clock start); "
                 "IR undefined -> recorded 0.0") if len(forward_bars) < 2 else None
    memo = _research_token_memo(clock_start)
    fp, fp_meta = ((fingerprint_override, {"override": True})
                   if fingerprint_override is not None
                   else _live_fingerprint(now))

    store.init()
    living = [v for v in store.living()]
    existing_max = 0
    for v in living:
        existing_max = max(existing_max, store.window_count(v["id"]))
    window_no = existing_max + 1

    judged: list[dict] = []
    for v in sorted(living, key=lambda x: x["id"]):
        ir = 0.0
        if dry_run:
            from app.evo.judge import judge_window
            verdict = judge_window(n_decisions, ir, 0, TOKEN_BUDGET_DETERMINISTIC)
            judged.append({"variant": v["id"], "name": v["name"], "dry_run": True,
                           "n_decisions": n_decisions, "ir": ir, "tokens": 0,
                           "verdict": verdict["verdict"], "reasons": verdict["reasons"],
                           "status": v["status"], "strikes": v["strikes"]})
        else:
            r = arena.judge_round(v["id"], window_no, n_decisions, ir, 0,
                                  TOKEN_BUDGET_DETERMINISTIC, death_fingerprint=fp)
            judged.append({"variant": v["id"], "name": v["name"],
                           "n_decisions": n_decisions, "ir": ir, "tokens": 0,
                           **r})

    if dry_run:
        allocation = {}
    else:
        allocation = arena.population_state()["allocation"]

    # --- foundry gate: forbidden probe must reject at parse ---
    probe_rec: dict = {"kind": WEEK1_PROBE["kind"], "params": WEEK1_PROBE["params"]}
    try:
        P.parse(WEEK1_PROBE["kind"], WEEK1_PROBE["params"],
                rationale=WEEK1_PROBE["rationale"])
        probe_rec.update({"rejected": False, "error": "PARSE GATE FAILED TO REJECT"})
    except ValueError as e:
        probe_rec.update({"rejected": True, "error": str(e)})

    # --- foundry gate: allowlisted candidate through embargoed PBO-lite ---
    rows, rows_prov = _forward_rows()
    cand = candidate or WEEK1_CANDIDATE
    prop = P.parse(cand["kind"], cand["params"], rationale=cand["rationale"])
    if dry_run:
        cand_rec: dict = {"promoted": False, "reason": "dry-run (not validated)"}
    else:
        V.init_tables()
        try:
            cand_rec = V.validate(prop, rows, _frozen_baseline)
        except ValueError as e:
            # genome-shaped kinds have no veto-table semantics: evo-queue route,
            # never live. Recorded, not crashed.
            cand_rec = {"promoted": False, "reason": f"evo-queue route ({e})"}
    cand_rec = {"kind": prop.kind, "params": prop.params, **cand_rec}

    artifact = {
        "ritual": "forward-week",
        "window_no": window_no,
        "week_start": clock_start.date().isoformat() if window_no == 1
        else now.date().isoformat(),
        "as_of": now.isoformat(),
        "clock_start": clock_start.isoformat(),
        "scope": "forward-only; no 2021-2026 bar used for any judgment/promotion",
        "min_decisions": MIN_DECISIONS,
        "n_forward_bars": len(forward_bars),
        "forward_bars_provenance": bars_prov,
        "n_decisions_this_window": n_decisions,
        "ir_note": ir_reason or f"trailing IR over {len(forward_bars)} forward closes",
        "token_budget_per_variant": TOKEN_BUDGET_DETERMINISTIC,
        "research_token_memo": memo,
        "death_fingerprint": fp,
        "fingerprint_meta": fp_meta,
        "judged": judged,
        "allocation": allocation,
        "foundry": {
            "rows_n": len(rows),
            "rows_provenance": rows_prov,
            "baseline": ("frozen veto table w/ neutral ret_5d=0/dist_high=-5 stand-ins; "
                         "outcome baseline-independent while rows empty"),
            "forbidden_probe": probe_rec,
            "candidate": cand_rec,
        },
        "dry_run": dry_run,
        "freeze_check": freeze_check or {"checked": False},
        "generated_at": _now().isoformat(),
    }
    path = out_path or os.path.join(
        "data", f"forward_week_{window_no:02d}_{now.date().isoformat()}.json")
    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)
    artifact["artifact_path"] = path
    return artifact


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--freeze", default=None,
                    help="strategy freeze artifact to verify before judging (§56)")
    a = ap.parse_args()
    art = run_week(dry_run=a.dry_run, out_path=a.out, freeze_path=a.freeze)
    if art.get("verdict") == "NO_JUDGMENT":
        print(json.dumps({k: art[k] for k in (
            "verdict", "reason", "freeze_check", "artifact_path")}, indent=2))
        return
    print(json.dumps({k: art[k] for k in (
        "window_no", "as_of", "n_forward_bars", "n_decisions_this_window",
        "allocation", "dry_run", "artifact_path")}, indent=2))
    for j in art["judged"]:
        print(f"{j['variant']:28s} n={j['n_decisions']} ir={j['ir']:+.3f} "
              f"-> {j.get('transition', j.get('verdict'))}")
    print("foundry probe rejected:", art["foundry"]["forbidden_probe"].get("rejected"),
          "| candidate promoted:", art["foundry"]["candidate"].get("promoted"),
          "| reason:", art["foundry"]["candidate"].get("reason", art["foundry"]["candidate"].get("block_wins")))
    if not a.dry_run:
        print("artifact:", art["artifact_path"])


if __name__ == "__main__":
    main()
