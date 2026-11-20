"""W1.2 executable labels: decision -> next tradable fill -> horizon exit.

The label contract (V3.1 blueprint §6.2): a decision taken after a completed
close must be filled at the NEXT eligible tradable observation — never at the
already-known close that drove the decision. Missing observed prices are
``NO_FILL`` or an explicitly-labelled conservative extension, never an invented
perfect fill.

Money is integer paise throughout; charges come from the tested
``research_v3.economics`` adapter (paise-for-paise with the TS paper book).

Label semantics
---------------
entry  ``next_session_open_after_decision`` — first bar whose ``available_at``
       is strictly after the decision instant; reference price = that bar's
       open. The decision close is never used, so no same-close lookahead.
exit   ``horizon_sessions_close_conservative_extension`` — the close of the
       session ``h`` observed sessions after entry; if that session has no bar
       (halt/suspension/missing row) the exit extends to the next available
       close with ``exit_extended=True`` (labelled conservative simulation);
       ``NO_FILL`` when no bar appears within ``MAX_WAIT_SESSIONS``.
return ``v3_trade_cash_pnl`` (integer-paise cash) + ``v3_net_absolute`` +
       ``v3_benchmark_relative`` (excess vs official TRI over the same window,
       never displayed as cash profit).
"""
from __future__ import annotations

from . import economics
from . import warehouse as W

DEFAULT_NOTIONAL_PAISE = 10_000_000  # Rs 1,00,000 of entry value
ENTRY_POLICY = "next_session_open_after_decision"
EXIT_POLICY = "horizon_sessions_close_conservative_extension"
MAX_WAIT_SESSIONS = 5


def _latest_available_bar(conn, symbol: str, decision_ts: str) -> W.Bar | None:
    res = W.bars_asof(conn, symbol, decision_ts)
    if res.status != "OK":
        return None
    session, o, h, l, c, pc, vol, val, tr, avail, isin, series = res.rows[-1]
    return W.Bar(session=session, symbol=symbol, series=series, isin=isin,
                 open_paise=o, high_paise=h, low_paise=l, close_paise=c,
                 prev_close_paise=pc, volume=vol, value_paise=val, trades=tr,
                 source_id="nse_eod_bhavcopy_2015_2026_full",
                 published_at=session, first_seen_at=W.BHAVCOPY_ARCHIVE_BUILT_ON,
                 available_at=avail,
                 adjustment_basis="unadjusted official bhavcopy prices (raw exchange record)",
                 source_class=W.SOURCE_CLASS_BHAVCOPY)


def _bar_on(conn, symbol: str, session: str):
    row = conn.execute(
        "SELECT open_paise, close_paise, available_at, series FROM daily_bars "
        "WHERE symbol=? AND session=? AND series=? ORDER BY series", (symbol, session, "EQ")).fetchone()
    return row


def executable_label(conn, symbol: str, decision_ts: str, horizon_sessions: int,
                     *, notional_paise: int = DEFAULT_NOTIONAL_PAISE,
                     max_wait_sessions: int = MAX_WAIT_SESSIONS,
                     broker: str = "book_zero_brokerage",
                     observed_sessions: list[str] | None = None,
                     exit_ref: str = "CLOSE") -> dict:
    """Build one executable label with explicit status and zero fabrication.

    Statuses: ``NO_DECISION_BASELINE`` (no bar available at the decision),
    ``NO_FILL`` (no tradable observation appeared after the decision within the
    wait window), ``OK``.

    ``observed_sessions`` is an optional precomputed ascending list of the
    warehouse's distinct sessions (``warehouse.sessions``) — a pure speed-up
    for portfolio-scale runs; semantics are identical either way.

    ``exit_ref`` selects the exit price within the exit session: ``"CLOSE"``
    (default, single-trade horizon) or ``"OPEN"`` (rolling portfolios that
    re-enter at the next rebalance's open — the chain then rolls execution
    price to execution price with no skipped boundary move). The conservative
    labelled extension applies to the same reference price.
    """
    import bisect
    if horizon_sessions <= 0:
        raise ValueError("horizon_sessions must be positive")
    if exit_ref not in ("CLOSE", "OPEN"):
        raise ValueError("exit_ref must be 'CLOSE' or 'OPEN'")
    symbol = symbol.strip().upper()
    base = _latest_available_bar(conn, symbol, decision_ts)
    if base is None:
        return {"status": "NO_DECISION_BASELINE", "symbol": symbol,
                "decision_ts": decision_ts, "horizon_sessions": horizon_sessions,
                "note": "no bar was available at the decision cutoff; no label"}
    if base.close_paise <= 0:
        return {"status": "NO_DECISION_BASELINE", "symbol": symbol,
                "decision_ts": decision_ts, "note": "degenerate close at baseline"}

    # --- entry: first bar strictly AFTER the decision's availability ----------
    res = W.bars_asof(conn, symbol, "9999-12-31T23:59:59+00:00")
    if res.status != "OK":
        return {"status": "NO_FILL", "symbol": symbol, "decision_ts": decision_ts,
                "decision_baseline_session": base.session,
                "note": "no bars exist after the decision; nothing tradable"}
    entry = None
    for session, o, h, l, c, pc, vol, val, tr, avail, isin, series in res.rows:
        if avail > decision_ts:
            entry = (session, o, avail)
            break
    if entry is None:
        return {"status": "NO_FILL", "symbol": symbol, "decision_ts": decision_ts,
                "decision_baseline_session": base.session,
                "note": f"no tradable observation within available history "
                        f"(max_wait_sessions={max_wait_sessions})"}
    entry_session, entry_open_paise, entry_available = entry
    if entry_open_paise <= 0:
        return {"status": "NO_FILL", "symbol": symbol,
                "decision_baseline_session": base.session,
                "entry_session": entry_session, "note": "degenerate open; not fillable"}

    # --- exit: reference price of the session `horizon_sessions` sessions later
    if observed_sessions is None:
        following = [r[0] for r in conn.execute(
            "SELECT DISTINCT session FROM daily_bars WHERE session>? ORDER BY session",
            (entry_session,))]
    else:
        following = observed_sessions[bisect.bisect_right(observed_sessions, entry_session):]
    if len(following) < horizon_sessions:
        return {"status": "NO_FILL", "symbol": symbol, "entry_session": entry_session,
                "decision_ts": decision_ts,
                "note": f"history ends before the {horizon_sessions}-session horizon"}
    target_exit_session = following[horizon_sessions - 1]
    price_ix = 0 if exit_ref == "OPEN" else 1  # daily_bars row: (open, close, ...)
    exit_row = _bar_on(conn, symbol, target_exit_session)
    exit_session, exit_price_paise, exit_extended = target_exit_session, None, False
    if exit_row is None or exit_row[price_ix] <= 0:
        # conservative labelled extension: next available reference within the window
        for cand in following[horizon_sessions:horizon_sessions - 1 + max_wait_sessions]:
            r2 = _bar_on(conn, symbol, cand)
            if r2 is not None and r2[price_ix] > 0:
                exit_session, exit_price_paise, exit_extended = cand, r2[price_ix], True
                break
        if exit_price_paise is None:
            return {"status": "NO_FILL", "symbol": symbol, "entry_session": entry_session,
                    "decision_ts": decision_ts,
                    "note": f"no exit {exit_ref.lower()} within {max_wait_sessions} "
                            f"sessions of {target_exit_session}"}
    else:
        exit_price_paise = exit_row[price_ix]
    exit_close_paise = exit_price_paise

    # --- accounting: integer paise, exact charges -----------------------------
    qty = notional_paise // entry_open_paise
    if qty <= 0:
        return {"status": "NO_FILL", "symbol": symbol, "entry_session": entry_session,
                "note": "notional below one share at the executable open"}
    try:
        acct = economics.trade_cash_pnl(qty, entry_open_paise, exit_close_paise,
                                        entry_session + "T00:00:00+05:30",
                                        exit_session + "T00:00:00+05:30", broker=broker)
        charges_status = "OK"
    except ValueError as exc:
        if str(exc) != economics.ScheduleUnavailable:
            raise
        # Fee truth starts at the schedule's verified effective date; earlier
        # windows keep GROSS metrics only, with charges explicitly unavailable —
        # never silently priced with a later schedule.
        acct = None
        charges_status = "SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE"
    stock_gross = exit_close_paise / entry_open_paise - 1
    bench = W.benchmark_total_return(conn, "NIFTY50_TRI", entry_session, exit_session)
    benchmark_relative = stock_gross - bench["total_return"]
    label = {
        "status": "OK",
        "symbol": symbol,
        "decision_ts": decision_ts,
        "decision_baseline_session": base.session,
        "decision_baseline_close_paise": base.close_paise,
        "horizon_sessions": horizon_sessions,
        "entry": {"session": entry_session, "available_at": entry_available,
                  "ref_price_paise": entry_open_paise, "ref_kind": "OPEN",
                  "policy": ENTRY_POLICY},
        "next_eligible_entry_time": entry_available,
        "exit": {"session": exit_session, "ref_price_paise": exit_close_paise,
                 "ref_kind": exit_ref, "policy": EXIT_POLICY,
                 "extended": exit_extended},
        "next_eligible_exit_time": exit_session + "T00:00:00+05:30",
        "quantity": qty,
        "accounting": acct,
        "charges_status": charges_status,
        "v3_gross_absolute": stock_gross,
        "v3_benchmark_relative": benchmark_relative,
        "metric_versions": {"benchmark_relative": "v3_benchmark_relative",
                            "gross_absolute": "v3_gross_absolute"},
        "benchmark": {"index": bench["index"], "basis": bench["basis"],
                      "window": [bench["start_session"], bench["end_session"]],
                      "total_return": bench["total_return"]},
        "adjustment_treatment": "unadjusted prices; verified corporate actions would "
                                "require the factor check (UNKNOWN abstains)",
        "semantics": {
            "v3_benchmark_relative": "excess return vs benchmark; never display as profit",
            "v3_trade_cash_pnl": "absolute integer-paise cash P&L after itemised charges",
            "v3_net_absolute": "absolute net return after charges",
            "v3_gross_absolute": "price-only gross return before charges",
        },
        "claim": "RETROSPECTIVE label from official archived bars; not a forward prediction",
    }
    if acct is not None:
        label["metric_versions"].update(acct["metric_versions"])
    else:
        label["note"] = ("fee schedule does not cover these trade dates; net metrics "
                         "are withheld (None) rather than priced with a later schedule")
    return label
