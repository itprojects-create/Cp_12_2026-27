"""W3 label building: batch construction on top of the W1 executable-label
engine (single source of return truth — no second accounting).

Every label calls ``research_v3.labels.executable_label`` unchanged, then the
builder adds typed admissibility:

- status != OK            -> NO_LABEL (kept, excluded from IC/statistics);
- an action-shaped raw-price discontinuity (close/prev_close outside
  [0.65, 1.54]) inside the [entry, exit] window -> DATA_BLOCKED_ACTION_WINDOW:
  the economic return is not interpretable on raw unadjusted prices, so the
  label is excluded from cross-sectional statistics (IC/Brier/MAE) and only
  ever appears inside disclosed gross portfolio paths (contamination stays in
  returns — no upward bias), exactly mirroring the W2 discipline;
- verified-action windows are ALSO excluded from IC (one conservative rule for
  all discontinuities); their existence is disclosed per label.
"""
from __future__ import annotations

import sqlite3

from quantplus_intelligence.research_v3 import labels as L
from quantplus_intelligence.research_v3.quantlab.contracts import (
    ADMISSIBLE, DATA_BLOCKED_ACTION, NO_LABEL, ReturnLabel)
from quantplus_intelligence.research_v3.quantlab.features import FeaturePanel


def build_label(panel: FeaturePanel, symbol: str, decision_ts: str,
                horizon_sessions: int, *, exit_ref: str = "CLOSE",
                notional_paise: int = L.DEFAULT_NOTIONAL_PAISE) -> ReturnLabel:
    """One typed ReturnLabel from the W1 engine + discontinuity gate."""
    conn = panel.conn
    raw = L.executable_label(conn, symbol, decision_ts, horizon_sessions,
                             notional_paise=notional_paise,
                             observed_sessions=panel.sessions,
                             exit_ref=exit_ref)
    status = raw["status"]
    entry_session = raw.get("entry", {}).get("session") if status == "OK" \
        else raw.get("entry_session")
    exit_session = raw.get("exit", {}).get("session") if status == "OK" \
        else None
    gross = raw.get("v3_gross_absolute") if status == "OK" else None
    contam = tuple(panel.holding_discontinuities(symbol, entry_session,
                                                 exit_session)) \
        if (entry_session and exit_session) else ()
    if status != "OK" or gross is None:
        admissibility = NO_LABEL
    elif contam:
        admissibility = DATA_BLOCKED_ACTION
    else:
        admissibility = ADMISSIBLE
    acct = raw.get("accounting")
    bench_raw = raw.get("v3_benchmark_relative") if status == "OK" else None
    visible_date = (raw.get("decision_baseline_session") or decision_ts)[:10]
    return ReturnLabel(
        symbol=symbol, decision_ts=decision_ts,
        decision_session=raw.get("decision_baseline_session", ""),
        horizon_sessions=horizon_sessions, admissibility=admissibility,
        status=status, entry_session=entry_session, exit_session=exit_session,
        exit_extended=bool(raw.get("exit", {}).get("extended", False))
        if status == "OK" else False,
        gross_return=gross,
        net_absolute_paise=(acct.get("v3_trade_cash_pnl_paise")
                            if acct else None),
        charges_status=raw.get("charges_status", "UNAVAILABLE"),
        benchmark_relative="DATA_BLOCKED_BASIS_MISMATCH"
        if status == "OK" else "NO_BENCHMARK",
        benchmark_relative_raw=bench_raw,
        contamination=contam,
        membership_strict=bool(panel.spell_strict(symbol, visible_date)))


def build_labels(panel: FeaturePanel, decisions: list[tuple[str, str]],
                 horizons: tuple[int, ...], *, exit_ref: str = "CLOSE",
                 progress=None) -> dict[tuple[str, str, int], ReturnLabel]:
    """Batch labels for (decision_session, symbol) pairs.

    ``decisions`` items are (decision_session, symbol); the decision
    timestamp is derived from the W1 availability rule the panel already
    uses: the first bar available AFTER the decision session's availability,
    i.e. decision_ts = next session's first-bar available_at boundary. To
    keep the W1 engine authoritative the caller passes explicit
    decision_ts values; ``decisions`` items may be (session, symbol) with
    session == the visible session and the timestamp built as
    ``session T00:15:00+05:30 next day`` by the orchestrator (same T00:15
    IST convention W2 uses).
    """
    out: dict[tuple[str, str, int], ReturnLabel] = {}
    total = len(decisions) * len(horizons)
    done = 0
    for session, symbol in decisions:
        decision_ts = _decision_ts(session)
        for h in horizons:
            out[(symbol, session, h)] = build_label(
                panel, symbol, decision_ts, h, exit_ref=exit_ref)
            done += 1
            if progress and done % progress == 0:
                print(f"  labels {done}/{total}", flush=True)
    return out


def _decision_ts(session: str) -> str:
    """Decision instant for a visible session: T00:15:00+05:30 of the NEXT
    local day (the W2 availability rule: decision sees prior session close)."""
    from datetime import date, timedelta
    d = date.fromisoformat(session[:10]) + timedelta(days=1)
    return f"{d.isoformat()}T00:15:00+05:30"
