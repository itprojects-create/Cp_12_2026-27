"""Honest result panels (W6.4): skill, absolute economics, investor-relative.

Three independent views, never mixed:
  A  forecast/classification skill: date-clustered rank IC, Brier where valid,
     effective independent date count, GOLDSET_HOLDOUT_UNAVAILABLE without
     real blind labels.
  B  absolute portfolio economics: paper NAV with mark provenance, gross/net
     split, drawdown, turnover, per-order audit; DATA_BLOCKED where inputs are
     missing (a missing date is never an implicit zero).
  C  investor-relative: date-aligned comparison against separately reported
     cash, verified TRI and simple controls; basis mismatch is labelled, and
     small samples are labelled INSUFFICIENT_FORWARD_SAMPLE.

The default financial verdict is NOT_YET_DEMONSTRATED until preregistered
rules, sufficient independent evidence, and input integrity all pass.
"""
from __future__ import annotations

import math
from typing import Any

VERDICT_NOT_YET_DEMONSTRATED = "NOT_YET_DEMONSTRATED"
VERDICT_INSUFFICIENT_FORWARD_SAMPLE = "INSUFFICIENT_FORWARD_SAMPLE"
VERDICT_DATA_BLOCKED = "DATA_BLOCKED"
VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE = "GOLDSET_HOLDOUT_UNAVAILABLE"
VERDICT_DATA_BLOCKED_BASIS_MISMATCH = "DATA_BLOCKED_BASIS_MISMATCH"


def _pct(x: float) -> float:
    return x * 100.0


def rank_ic_by_date(scored: list[dict]) -> dict:
    """Date-clustered Spearman rank IC.

    ``scored`` rows need: session_date, score, forward_return (a label
    generated AFTER the cutoff; supplied by the caller from a separate,
    outcome-labelled table — never stored inside decision records).
    """
    by_date: dict[str, list[tuple[float, float]]] = {}
    for row in scored:
        if row.get("score") is None or row.get("forward_return") is None:
            continue
        by_date.setdefault(row["session_date"], []).append(
            (float(row["score"]), float(row["forward_return"])))
    daily_ics: list[tuple[str, float, int]] = []
    for session, pairs in sorted(by_date.items()):
        if len(pairs) < 2:
            continue
        ic = _spearman(pairs)
        if ic is not None:
            daily_ics.append((session, ic, len(pairs)))
    if not daily_ics:
        return {"metric": "rank_ic", "status": VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE,
                "n_effective_dates": 0,
                "note": "no labelled forward returns available; no IC computed"}
    values = [ic for _, ic, _ in daily_ics]
    n_dates = len(daily_ics)
    mean_ic = sum(values) / n_dates
    variance = sum((v - mean_ic) ** 2 for v in values) / max(1, n_dates - 1)
    se = math.sqrt(variance / n_dates) if n_dates > 1 else None
    t_stat = (mean_ic / se) if se and se > 0 else None
    return {"metric": "rank_ic", "status": "COMPUTED",
            "mean_daily_ic": mean_ic,
            "daily_ics": [{"session_date": s, "ic": ic, "n": n}
                          for s, ic, n in daily_ics],
            "n_effective_dates": n_dates,
            "se_date_clustered": se,
            "t_stat_date_clustered": t_stat,
            "note": "date-clustered; same-day stock observations are NOT "
                    "independent trials"}


def _spearman(pairs: list[tuple[float, float]]) -> float | None:
    ranks_x = _ranks([p[0] for p in pairs])
    ranks_y = _ranks([p[1] for p in pairs])
    n = len(pairs)
    mean_x = sum(ranks_x) / n
    mean_y = sum(ranks_y) / n
    cov = sum((rx - mean_x) * (ry - mean_y) for rx, ry in zip(ranks_x, ranks_y))
    var_x = sum((rx - mean_x) ** 2 for rx in ranks_x)
    var_y = sum((ry - mean_y) ** 2 for ry in ranks_y)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def brier_scores(rows: list[dict]) -> dict:
    """Brier for probability forecasts; needs real blind labels."""
    valid = [(float(r["p"]), float(r["label"])) for r in rows
             if r.get("p") is not None and r.get("label") is not None
             and 0.0 <= float(r["p"]) <= 1.0 and float(r["label"]) in (0.0, 1.0)]
    if not valid:
        return {"metric": "brier", "status": VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE,
                "note": "no real blind labels; no calibration claim"}
    return {"metric": "brier", "status": "COMPUTED",
            "n": len(valid),
            "brier": sum((p - y) ** 2 for p, y in valid) / len(valid)}


def nav_series(ledger, stream_id: str) -> dict:
    """Panel B: NAV series from ValuationMark + CashFlow evidence only.

    Sessions without a complete mark set are reported as missing, never
    implicitly zero.
    """
    marks: dict[str, dict[str, dict]] = {}   # symbol -> session -> mark payload
    for event in ledger.stream_records(stream_id, "VALUATION_MARK"):
        payload = event["payload"]
        if payload["status"] != "MARK_OBSERVED":
            continue
        session = payload.get("session_date") or \
            payload["recorded_at"][:10]
        marks.setdefault(payload["symbol"], {})[session] = payload
    flows = [event["payload"]
             for event in ledger.stream_records(stream_id, "CASH_FLOW")]
    fees = [event["payload"]
            for event in ledger.stream_records(stream_id, "FEE_EVENT")]
    fills = [event["payload"]
             for event in ledger.stream_records(stream_id, "FILL_EVENT")]
    sessions = sorted({s for series in marks.values() for s in series})
    series: list[dict] = []
    for session in sessions:
        components = []
        for symbol, by_session in marks.items():
            mark = by_session.get(session)
            components.append({
                "symbol": symbol, "mark_paise": mark["mark_paise"],
                "mark_source": mark["mark_source"], "mark_time": mark["mark_time"],
                "quantity": mark["quantity"]})
        series.append({"session_date": session, "marks": components})
    trade_count = sum(1 for f in fills
                      if f["fill_status"] in ("FILLED", "PARTIAL_FILL"))
    fees_paid = sum(f["total_paise"] for f in fees)
    turnover = sum(f["filled_quantity"] * f["price_paise"] for f in fills
                   if f["fill_status"] in ("FILLED", "PARTIAL_FILL"))
    return {
        "panel": "B_absolute_economics",
        "status": ("COMPUTED" if series else VERDICT_DATA_BLOCKED),
        "n_marked_sessions": len(series),
        "sessions_without_complete_marks":
            "reported per NAV computation; a missing mark is never a zero",
        "series": series,
        "trade_count": trade_count,
        "fees_paid_paise": fees_paid,
        "turnover_paise": turnover,
        "cash_flows": flows,
        "note": "NAV/equity themselves are computed by the book's verified "
                "reconciliation; this panel reports the observable evidence",
    }


def absolute_economics(nav_rows: list[dict], *, fills: list[dict],
                       fees: list[dict], blocked_valuations: list[dict] | None = None,
                       starting_capital_paise: int | None = None) -> dict:
    """Panel B summary with absolute gross/net kept distinct.

    ``nav_rows`` require complete, independently reconciled ``equity_paise``.
    Missing/blocked marks make the result DATA_BLOCKED rather than a zero return.
    """
    blocked = list(blocked_valuations or [])
    complete = [row for row in nav_rows
                if row.get("equity_paise") is not None and row.get("nav_known") is True]
    result: dict[str, Any] = {
        "panel": "B_absolute_economics", "n_complete_marks": len(complete),
        "n_blocked_marks": len(blocked), "blocked_valuations": blocked,
        "trade_count": sum(1 for row in fills
                           if row.get("fill_status") in ("FILLED", "PARTIAL_FILL")),
        "fees_paid_paise": sum(int(row.get("total_paise", 0)) for row in fees),
        "turnover_paise": sum(int(row.get("executed_value_paise", 0)) for row in fills
                              if row.get("fill_status") in ("FILLED", "PARTIAL_FILL")),
    }
    if blocked or len(complete) < 1 or starting_capital_paise is None:
        result.update({"status": VERDICT_DATA_BLOCKED,
                       "absolute_net_return": None,
                       "note": "missing/blocked marks or starting capital; no zero return imputed"})
        return result
    last = complete[-1]["equity_paise"]
    result.update({
        "status": "COMPUTED_DESCRIPTIVE",
        "starting_capital_paise": starting_capital_paise,
        "ending_equity_paise": last,
        "absolute_net_pnl_paise": last - starting_capital_paise,
        "absolute_net_return": last / starting_capital_paise - 1,
        "drawdown": drawdown([row["equity_paise"] for row in complete]),
        "verdict": VERDICT_NOT_YET_DEMONSTRATED,
        "note": "descriptive paper accounting only; not evidence of profitable alpha",
    })
    return result


def drawdown(equity_values: list[float]) -> dict:
    if not equity_values:
        return {"max_drawdown": None, "status": VERDICT_DATA_BLOCKED}
    peak = equity_values[0]
    max_dd = 0.0
    for value in equity_values:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return {"max_drawdown": max_dd, "status": "COMPUTED"}


def benchmark_relative(ledger, stream_id: str, *,
                       portfolio_values: list[dict],
                       benchmark_values: list[dict]) -> dict:
    """Panel C: investor-relative on a date-aligned, compatible basis.

    portfolio_values rows: session_date, value_paise (or None)
    benchmark_values rows: session_date, value (index level), basis,
    comparability (COMPARABLE / BASIS_MISMATCH / UNAVAILABLE)
    """
    bench_by_session = {row["session_date"]: row for row in benchmark_values}
    aligned: list[dict] = []
    basis_mismatch = False
    bench_available = bool(benchmark_values)
    for row in portfolio_values:
        bench = bench_by_session.get(row["session_date"])
        if bench is None or bench.get("comparability") == "UNAVAILABLE":
            aligned.append({"session_date": row["session_date"],
                            "status": "BENCHMARK_MISSING",
                            "portfolio_value_paise": row.get("value_paise")})
            continue
        if bench.get("comparability") == "BASIS_MISMATCH":
            basis_mismatch = True
        aligned.append({"session_date": row["session_date"],
                        "status": "ALIGNED",
                        "portfolio_value_paise": row.get("value_paise"),
                        "benchmark_value": bench.get("value"),
                        "benchmark_basis": bench.get("basis"),
                        "comparability": bench.get("comparability")})
    result: dict[str, Any] = {
        "panel": "C_investor_relative",
        "aligned_rows": aligned,
        "n_aligned": sum(1 for a in aligned if a["status"] == "ALIGNED"),
        "n_benchmark_missing": sum(1 for a in aligned
                                   if a["status"] == "BENCHMARK_MISSING"),
    }
    if basis_mismatch:
        result["status"] = VERDICT_DATA_BLOCKED_BASIS_MISMATCH
        result["note"] = (
            "portfolio and benchmark basis are not compatible (e.g. price-only "
            "portfolio vs total-return index); a validated excess return is "
            "NOT claimed and context is shown separately")
        return result
    if not bench_available or result["n_aligned"] < 2:
        result["status"] = VERDICT_DATA_BLOCKED
        result["note"] = "no verified forward benchmark marks for the interval"
        return result
    # Same-basis growth comparison where both ends exist.
    p_first = next((r for r in aligned if r["status"] == "ALIGNED"
                    and r.get("portfolio_value_paise") is not None), None)
    p_last = next((r for r in reversed(aligned) if r["status"] == "ALIGNED"
                   and r.get("portfolio_value_paise") is not None), None)
    b_first = next((r for r in aligned if r["status"] == "ALIGNED"), None)
    b_last = next((r for r in reversed(aligned) if r["status"] == "ALIGNED"), None)
    if not (p_first and p_last and b_first and b_last and
            p_first is not p_last and b_first is not b_last and
            p_first.get("portfolio_value_paise") and
            b_first.get("benchmark_value")):
        result["status"] = VERDICT_DATA_BLOCKED
        result["note"] = "insufficient aligned endpoints"
        return result
    portfolio_return = (p_last["portfolio_value_paise"] /
                        p_first["portfolio_value_paise"]) - 1
    benchmark_return = (b_last["benchmark_value"] /
                        b_first["benchmark_value"]) - 1
    result["status"] = "COMPUTED_DESCRIPTIVE"
    result["portfolio_return"] = portfolio_return
    result["benchmark_return"] = benchmark_return
    result["relative_difference"] = portfolio_return - benchmark_return
    result["portfolio_basis"] = "PAPER_NAV_CASH_ACCOUNTING"
    result["benchmark_basis"] = b_first.get("benchmark_basis")
    result["verdict"] = VERDICT_NOT_YET_DEMONSTRATED
    result["note"] = (
        "descriptive only; positive relative difference is NOT positive "
        "absolute profit and NOT validated alpha")
    return result


def result_panels(*, scored: list[dict], probabilities: list[dict],
                  nav_rows: list[dict], fills: list[dict], fees: list[dict],
                  blocked_valuations: list[dict], starting_capital_paise: int | None,
                  benchmark_rows: list[dict], n_independent_horizons: int,
                  minimum_horizons: int) -> dict:
    """Build the mandatory A/B/C views without cross-labelling their claims."""
    portfolio_rows = [{"session_date": row["session_date"],
                       "value_paise": row.get("equity_paise")}
                      for row in nav_rows]
    return {
        "panel_A_forecast_skill": {
            "rank_ic": rank_ic_by_date(scored),
            "brier": brier_scores(probabilities),
            "event_classifier": {"status": VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE},
        },
        "panel_B_absolute_economics": absolute_economics(
            nav_rows, fills=fills, fees=fees,
            blocked_valuations=blocked_valuations,
            starting_capital_paise=starting_capital_paise),
        "panel_C_investor_relative": benchmark_relative(
            None, "", portfolio_values=portfolio_rows,
            benchmark_values=benchmark_rows),
        "sample_sufficiency": sample_sufficiency(
            n_independent_horizons, minimum_horizons),
        "financial_verdict": VERDICT_NOT_YET_DEMONSTRATED,
    }


def sample_sufficiency(n_independent_horizons: int, minimum: int) -> dict:
    if n_independent_horizons < minimum:
        return {"status": VERDICT_INSUFFICIENT_FORWARD_SAMPLE,
                "n_independent_horizons": n_independent_horizons,
                "minimum_preregistered": minimum}
    return {"status": "SUFFICIENT_FOR_DESCRIPTIVE_REPORTING_ONLY",
            "n_independent_horizons": n_independent_horizons,
            "minimum_preregistered": minimum}


def default_verdict() -> str:
    return VERDICT_NOT_YET_DEMONSTRATED
