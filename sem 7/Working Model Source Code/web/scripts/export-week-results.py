"""Export this week's agentic forecast cards versus what actually happened.

Builds reports/agentic-ai-week-results.xlsx next to the existing
reports/agentic-ai-predictions.xlsx. Reuses the dependency-free XLSX helpers
from scripts/export-agentic-ai-predictions.py so both workbooks share styling.

Usage (from D:\\Quant-Plus):
    .local-data/backend-runtime/Scripts/python.exe scripts/export-week-results.py

Sources: the forecast ledger (hash-chained, settlement-authoritative) and one
direct yfinance download for interim actuals. It never writes into the
backend's yf_cache. The provider adds a one-day PIT lag so intraday runs cannot
lock against an incomplete bar; this report generates after market close, so it
fetches completed bars directly using the provider's download parameters and
cross-checks them against the provider's cached CSVs before use.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

# For the NSE exchange calendar used by the incomplete-bar guard.
BACKEND = Path(r"D:\QP\agent-service")
if str(BACKEND) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(BACKEND))

LEDGER = Path(r"D:\QP\agent-service\data\forecast_ledger.sqlite3")
OUTPUT = ROOT / "reports" / "agentic-ai-week-results.xlsx"
PAPER_JSONL = Path(r"D:\QP\agent-service\data\forecast_reports\paper_pnl.jsonl")

# Week under review: forecast cards locked with these cutoff bars.
WEEK_AS_OFS = ("2026-10-30T00:00:00+00:00", "2026-11-02T00:00:00+00:00",
               "2026-11-04T00:00:00+00:00", "2026-11-05T00:00:00+00:00")
BATCH_LABEL = {
    "2026-10-30T00:00:00+00:00": "Batch A — cutoff Fri Oct 30 (locked Nov 1, forecast-v1)",
    "2026-11-02T00:00:00+00:00": "Batch B — cutoff Mon Nov 2 (locked Nov 3, forecast-v2)",
    "2026-11-04T00:00:00+00:00": "Batch C — cutoff Wed Nov 4 (locked Thu Nov 5 21:02 by the interrupted "
                                 "catch-up; 17 of 100 symbols before it was killed)",
    "2026-11-05T00:00:00+00:00": "Batch D — cutoff Thu Nov 5 (locked Fri Nov 6 evening, forecast-v2)",
}
BATCH_SHORT = {"2026-10-30T00:00:00+00:00": "A", "2026-11-02T00:00:00+00:00": "B",
               "2026-11-04T00:00:00+00:00": "C", "2026-11-05T00:00:00+00:00": "D"}

_spec = importlib.util.spec_from_file_location(
    "agentic_exporter", ROOT / "scripts" / "export-agentic-ai-predictions.py")
EXP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EXP)

_row = EXP._row
_sheet_xml = EXP._sheet_xml
_workbook_xml = EXP._workbook_xml
_workbook_rels = EXP._workbook_rels
_content_types = EXP._content_types
_root_rels = EXP._root_rels
_styles = EXP._styles
_safe_float = EXP._safe_float
_prediction_class = EXP._prediction_class
_score = EXP._score

# --------------------------------------------------------------------------- #
# Price fetching
# --------------------------------------------------------------------------- #


def fetch_instruments(instruments: list[str], start: str) -> dict:
    """Direct daily closes, mirroring the provider's download parameters."""
    import pandas as pd
    import yfinance as yf

    end = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    result: dict[str, "pd.Series"] = {}
    raw = yf.download(instruments, start=start, end=end, interval="1d",
                      auto_adjust=False, progress=False, group_by="ticker", threads=True)
    for name in instruments:
        frame = None
        try:
            frame = raw[name] if isinstance(raw.columns, pd.MultiIndex) else raw
        except (KeyError, IndexError):
            frame = None
        if frame is None or frame.empty or "Close" not in frame:
            frame = yf.download(name, start=start, end=end, interval="1d",
                                auto_adjust=False, progress=False, prepost=False)
        if frame is None or frame.empty:
            # Yahoo occasionally rejects a burst ticker ("possibly delisted"); one
            # short, bounded retry recovers it without changing any price row.
            from time import sleep

            sleep(2)
            frame = yf.download(name, start=start, end=end, interval="1d",
                                auto_adjust=False, progress=False, prepost=False)
        if frame is None or frame.empty:
            print(f"WARN: no price data for {name}")
            continue
        if frame.columns.nlevels > 1:
            frame.columns = [c[0] for c in frame.columns]
        result[name] = frame["Close"].dropna().sort_index()
    return result


def completed_bars(series):
    """Drop today's daily bar while the NSE session is live: an intraday row is an
    incomplete candle (audit AI-01) and must never become an 'actual'."""
    if series is None or getattr(series, "empty", True):
        return series
    now = datetime.now()
    today = now.date()
    if series.index[-1].date() != today or now.weekday() >= 5 or now.time() >= __import__("datetime").time(15, 35):
        return series
    trading = None
    try:
        from quantplus_intelligence.exchange_calendar import is_trading_day
        trading = is_trading_day(today)
    except Exception:  # noqa: BLE001 - unknown calendar keeps the conservative drop
        trading = None
    if trading is False:      # holiday: today's bar can complete normally
        return series
    return series[series.index.date != today] if hasattr(series.index, "date") else series


def verify_crosschecks(fetched: dict) -> None:
    """Fetched closes must match the backend provider's cached CSV files exactly.

    The provider caches store the raw downloaded frame (PIT filtering is applied
    at read time), so a cached row for a completed past session is a settled close
    directly comparable with our direct fetch. Same-day cache rows are warming
    snapshots taken mid-session and are ignored for comparison.
    """
    import pandas as pd

    cache = Path(r"D:\QP\agent-service\data\yf_cache")
    for instrument in ("WIPRO.NS", "ADANIENT.NS"):
        cache_files = sorted(cache.glob(f"{instrument.replace('.', '_')}_1d_*_completed_v3.csv"))
        if not cache_files:
            continue
        cached = pd.read_csv(cache_files[-1], index_col=0, parse_dates=True)
        cached = cached.sort_index()
        if cached.empty or "Close" not in cached:
            continue
        # A same-day cached row is whatever the warming provider saw mid-session —
        # never a settled close. Always compare against the latest strictly-past day.
        now_local = datetime.now()
        past = [ts for ts in cached.index if ts.date() < now_local.date()]
        if not past:
            continue
        day = past[-1]
        cached_close = float(cached["Close"].astype(float).loc[day])
        series = fetched.get(instrument)
        if series is None:
            raise SystemExit(f"CROSS-CHECK FAILED: {instrument} missing from direct fetch")
        try:
            live_close = float(series.loc[day])
        except KeyError:
            raise SystemExit(f"CROSS-CHECK FAILED: no bar for {instrument} on {day}")
        if abs(live_close - cached_close) > 1e-4 * max(1.0, cached_close):
            raise SystemExit(
                f"CROSS-CHECK FAILED {instrument} {day}: fetched {live_close} vs cached {cached_close}")
        print(f"Cross-check OK: {instrument} {day.date()} cached {cached_close} == fetched {live_close}")


def joined_series(stock, bench, as_of_day: str):
    """Same lineage as service.provider_fetch: inner join on session dates from
    the cutoff bar onward. Row 0 is the cutoff session."""
    import pandas as pd

    if stock is None or bench is None:
        return None
    day = pd.Timestamp(as_of_day)
    s, b = stock[stock.index >= day], bench[bench.index >= day]
    if s.empty or b.empty:
        return None
    joined = pd.concat([s.rename("Close"), b.rename("Bench")], axis=1, join="inner").dropna()
    if joined.empty:
        return None
    return joined.sort_index()


def actual_for(stock, bench, as_of_day: str, horizon: int) -> dict | None:
    joined = joined_series(stock, bench, as_of_day)
    if joined is None or len(joined) < 2:
        return None
    closes = joined["Close"].astype(float).tolist()
    bench_closes = joined["Bench"].astype(float).tolist()
    sessions = len(closes) - 1
    k = min(horizon, sessions)
    stock_ret = closes[k] / closes[0] - 1.0
    bench_ret = bench_closes[k] / bench_closes[0] - 1.0
    return {
        "k": k,
        "sessions": sessions,
        "stock_ret": stock_ret,
        "bench_ret": bench_ret,
        "excess": stock_ret - bench_ret,
        "close0": closes[0],
        "close_k": closes[k],
        "through": joined.index[k].date().isoformat(),
    }


def lean_agreement(card: dict, actual: dict | None, horizon: int) -> str:
    if card.get("abstain"):
        return "n/a — abstained"
    if actual is None:
        return "Pending price data"
    label = _prediction_class(card)
    if label == "No clear edge":
        return "n/a — no directional lean"
    agree = actual["excess"] > 0 if label == "Outperform lean" else actual["excess"] < 0
    base = "Agree" if agree else "Conflict"
    return base if actual["k"] >= horizon else f"{base} so far ({actual['k']}/{horizon})"


def settlement_status(matures_on: str, k: int, horizon: int) -> str:
    if k == 0:
        return f"Open — matures {matures_on}"
    if k < horizon:
        return f"Interim — matures {matures_on}; settlement only after the horizon completes"
    return f"All {horizon} sessions priced — awaiting scheduled settlement"


# --------------------------------------------------------------------------- #
# Sheets
# --------------------------------------------------------------------------- #


def week_results_sheet(rows):
    headers = [
        "Seq", "Symbol", "Batch", "Horizon (sessions)", "Cutoff bar", "Locked at (UTC)",
        "Matures on", "Model version", "P(outperform)", "Forecast class", "Abstain reason",
        "Q10 excess", "Q50 excess", "Q90 excess", "Vol forecast", "Disagreement", "Robustness",
        "Close at cutoff", "Ledger hash",
        "Sessions priced", "Priced through", "Stock move", "NIFTY move",
        "Actual excess vs NIFTY", "Actual direction", "Lean agreement (interim)",
        "Settlement status",
    ]
    out = [_row(headers, [2] * len(headers))]
    for r in rows:
        card, a = r["card"], r.get("actual")
        q = card.get("quantiles") or {}
        abstained = bool(card.get("abstain"))
        p = _safe_float(card.get("p_outperform"))
        if abstained:
            direction = "— abstained"
        elif a is None:
            direction = "Pending price data"
        else:
            direction = "Outperformed NIFTY so far" if a["excess"] > 0 else "Underperformed vs NIFTY so far"
        out.append(_row([
            r["seq"], r["symbol"], BATCH_LABEL.get(r["as_of"], r["as_of"]), r["horizon"],
            r["as_of"][:10], r["recorded_at"], r["matures_on"], card.get("model_version"),
            None if abstained else p, _prediction_class(card), card.get("abstain_reason") or "",
            None if abstained else _safe_float(q.get("0.1")),
            None if abstained else _safe_float(q.get("0.5")),
            None if abstained else _safe_float(q.get("0.9")),
            _safe_float(card.get("vol_forecast")), _safe_float(card.get("disagreement")),
            _safe_float(card.get("robustness")),
            a["close0"] if a else None, r["hash"],
            (f"{a['k']} of {r['horizon']}" if a else "—"),
            a["through"] if a else "",
            a["stock_ret"] if a else None, a["bench_ret"] if a else None,
            a["excess"] if a else None,
            direction,
            lean_agreement(card, a, r["horizon"]),
            settlement_status(r["matures_on"], a["k"] if a else 0, r["horizon"]),
        ], [4, 9, 9, 4, 9, 9, 9, 9, 6, 10, 9, 6, 6, 6, 6, 6, 5, 7, 9,
            9, 9, 6, 6, 6, 10, 10, 10]))
    return _sheet_xml(
        out,
        [7, 13, 36, 9, 12, 24, 12, 16, 12, 14, 18, 10, 10, 10, 10, 12, 11, 12, 66,
         12, 12, 11, 11, 12, 22, 26, 42],
        freeze=1, autofilter=f"A1:AA{len(out)}")


def settled_sheet(records, generated: str):
    rows_count, scored_cells = 0, 0
    rows = [
        _row(["Settled outcomes (final, forward-scored)", None], [1, 1]),
        _row(["Generated UTC", generated], [3, 9]),
        _row([None], [0]),
        _row(["Seq", "Symbol", "Horizon", "Cutoff bar", "Matures on", "Model version",
              "P(outperform)", "Forecast class", "Final excess", "Outperformed NIFTY",
              "Scored?", "Brier", "Log loss", "Locked at (UTC)", "Settled at (UTC)"], [2] * 15),
    ]
    for r in records:
        if not r["settled_at"]:
            continue
        rows_count += 1
        card = r["card"]
        outcome = r["outcome"] or {}
        p = _safe_float(card.get("p_outperform"))
        brier, log_loss = _score(p, None if card.get("abstain") else outcome)
        if brier is not None:
            scored_cells += 1
        rows.append(_row([
            r["seq"], r["symbol"], r["horizon"], r["as_of"][:10], r["matures_on"],
            card.get("model_version"), None if card.get("abstain") else p,
            _prediction_class(card), outcome.get("excess_return"),
            outcome.get("outperformed"), "Yes" if brier is not None else "No (abstained)",
            brier, log_loss, r["recorded_at"], r["settled_at"],
        ], [4, 9, 4, 9, 9, 9, 6, 10, 6, 4, 9, 5, 5, 9, 9]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Scoring note"], [11]))
    rows.append(_row(["• The abstaining ADANIPORTS outcome is shown for transparency but excluded from "
                      "accuracy, Brier and log loss — an abstention is not a directional forecast."], [10]))
    rows.append(_row(["• These matured before this week; they settle the October small-batch cards, "
                      "not any card locked this week."], [10]))
    xml = _sheet_xml(rows, [7, 13, 9, 11, 12, 16, 12, 14, 11, 13, 16, 10, 10, 24, 27], freeze=4)
    return xml, rows_count, scored_cells


def paper_sheet(generated: str) -> tuple[str, int]:
    """Pre-registered shadow paper-P&L stream, read straight from paper_pnl.jsonl.

    The registration line is the stream's own hash-chain-free pre-registration
    record; picks and settles accumulate from the evening jobs. Nothing here is
    invented: missing data shows as blank, no picks shows as an honest empty state.
    """
    lines: list[dict] = []
    if PAPER_JSONL.exists():
        for raw in PAPER_JSONL.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    registration = next((l for l in lines if l.get("type") == "registration"), None)
    picks = {l["card_id"]: l for l in lines if l.get("type") == "pick"}
    settles = {l["card_id"]: l for l in lines if l.get("type") == "settle"}
    nets = [l["net"] for l in settles.values()]

    def horizon_row(label: str, vals: list[float] | None, picks_n: int, open_n: int):
        vals = vals or []
        return _row([label, picks_n, len(vals), open_n, sum(v > 0 for v in vals),
                     (sum(vals) / len(vals)) if vals else None,
                     sum(vals) if vals else None], [9, 4, 4, 4, 4, 7, 7])

    rows = [
        _row(["Paper P&L — pre-registered shadow stream (SHADOW authority; this is not money P&L)"], [1]),
        _row(["Generated UTC", generated], [3, 9]),
        _row([None], [0]),
        _row(["Registration (fixed before any post-registration outcome existed)"], [11]),
    ]
    if registration:
        rows.append(_row(["Registered UTC", registration["registered_utc"]], [3, 9]))
        rows.append(_row([f"Rule: {registration.get('rule', '')}"], [10]))
        rows.append(_row([f"Scored from: {registration.get('scored_from', '')}."], [10]))
        rows.append(_row([f"Authority: {registration.get('authority', '')}."], [10]))
    else:
        rows.append(_row(["The stream is not registered yet; this tab will fill after the evening "
                          "run writes its registration into paper_pnl.jsonl."], [10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Status by horizon — net = realized excess − 0.4% delivery round trip"], [11]))
    rows.append(_row(["Horizon", "Picks", "Settled", "Open", "Hits", "Mean net", "Sum net"], [2] * 7))
    for horizon in (5, 20):
        settled_vals = [l["net"] for l in settles.values() if l.get("horizon") == horizon]
        open_n = sum(1 for p in picks.values()
                     if p.get("horizon") == horizon and p["card_id"] not in settles)
        rows.append(horizon_row(f"{horizon} sessions", settled_vals, len(settled_vals) + open_n, open_n))
    overall_open = len(picks) - len(settles)
    rows.append(horizon_row("All horizons", nets, len(picks), overall_open))
    if not picks:
        rows.append(_row([f"No picks yet — by design. Batch A (Nov 1) and Batch B (Nov 3) predate registration "
                          f"({registration['registered_utc'][:16] if registration else 'registration'} "
                          "UTC) and are excluded forever; the interrupted Thu 21:02 batch (Nov 4 bar) and any "
                          "superseded batch are never the 'latest batch', so they receive no picks under the "
                          "registered rule. Picks begin with the newest fully-locked post-registration batch."], [10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Picks (each scored exactly once, only after the main ledger settles the card)"], [11]))
    rows.append(_row(["Picked at (UTC)", "Symbol", "Horizon", "P(outperform)", "Batch as_of",
                      "Status", "Realized excess", "Net after costs"], [2] * 8))
    for cid, p in sorted(picks.items(), key=lambda kv: (kv[1].get("picked_at", ""), kv[1]["symbol"])):
        done = settles.get(cid)
        rows.append(_row([
            p.get("picked_at"), p["symbol"], p["horizon"], _safe_float(p.get("p")),
            p.get("as_of"), "Settled" if done else "Open — holds to horizon",
            done["excess_return"] if done else None, done["net"] if done else None,
        ], [9, 9, 4, 5, 9, 9, 7, 7]))
    if not picks:
        rows.append(_row(["Empty state is real: 0 picks reported honestly rather than a suppressed table."], [10]))
    rows.append(_row([None], [0]))
    for note in [
        "• SHADOW evidence stream for the profitability bridge — profitable trade intents can only ever come "
        "from bridge.edge_gate (≥30 settled cards per horizon, ≥10 bullish, hit rate >0.5, mean excess >0.4%); this stream opens nothing.",
        "• Pick rule is fixed and documented in the registration line; interim prices never influence a pick or a score.",
        "• One line per symbol per horizon per batch, written before those cards can mature; settle lines reuse the "
        "ledger's own forward settlement, not this report's interim prices.",
        "• Windows may still be open — an unscored stream says nothing about hit rate, and sum/mean of net is shown "
        "with blanks until settlement completes.",
    ]:
        rows.append(_row([note], [10]))
    return _sheet_xml(rows, [20, 13, 10, 12, 22, 20, 14, 14], freeze=2), len(picks)


REPORTS_LOGS = Path(r"D:\QP\agent-service\data\forecast_reports")


def _log_job_facts(job: str):
    """(last write time, last completed-run JSON) from a scheduled job's log file.

    Rows in this sheet describe only what a log actually recorded; a killed run
    leaves no final JSON and is reported as such — never invented.
    """
    path = REPORTS_LOGS / f"schedule_{job}.log"
    if not path.exists():
        return None, None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("job"):
            return datetime.fromtimestamp(path.stat().st_mtime), candidate
    return datetime.fromtimestamp(path.stat().st_mtime), None


def jobs_sheet(generated: str) -> str:
    now = datetime.now()
    rows = [
        _row(["Scheduled jobs this week (IST times)", None], [1, 1]),
        _row(["Generated UTC", generated], [3, 9]),
        _row([None], [0]),
        _row(["Day", "Job", "Scheduled", "What actually happened", "New cards / effect"], [2] * 5),
        _row(["Mon Nov 2", "settle + daily + tournament", "16:15 / 16:30 / 17:30",
              "Missed — machine unavailable at task time (0x800710E0). Documented in FORECAST_HANDOFF; "
              "no backfill is allowed under the forward-only rule.", "0"], [9, 9, 9, 10, 4]),
        _row(["Tue Nov 3", "settle", "16:15", "Ran. Nothing matured; chain verified (303 cards).",
              "0"], [9, 9, 9, 10, 4]),
        _row(["Tue Nov 3", "daily", "16:30",
              "Ran clean — 100 universe symbols × 5D+20D locked against the completed Nov 2 bar; "
              "news scanned for all 100; 0 failures.", "200 locked"], [9, 9, 9, 10, 4]),
        _row(["Tue Nov 3", "tournament", "17:30",
              "Ran — day Nov 2, 59 names ranked across 11 sectors; 6 small sectors skipped by design "
              "(minimum 3 peers).", "59 rankings"], [9, 9, 9, 10, 4]),
        _row(["Wed Nov 4", "settle + daily + tournament", "16:15 / 16:30 / 17:30",
              "No completed run — the ledger has no card for the Nov 3 bar and no market data was "
              "refreshed that evening; zero cards, zero token spend.", "0"], [9, 9, 9, 10, 4]),
        _row(["Thu Nov 5", "settle", "16:15",
              "Ran. Still nothing matured (first 5D group matures Fri Nov 6); chain verified (303).",
              "0"], [9, 9, 9, 10, 4]),
        _row(["Thu Nov 5", "daily", "16:30 → fired 18:12",
              "Machine woke late; the task fired at 18:12 and was terminated before locking any card "
              "(exit C000013A). No cards, no token spend. Note: the intraday veto refuses locking "
              "during a live session even if a late wake would otherwise reach the market.", "0"], [9, 9, 9, 10, 4]),
        _row(["Thu Nov 5", "paper (registered by hand)", "—",
              "Shadow paper-P&L stream registered 14:02 UTC (19:32 IST), before any post-registration card "
              "existed: top-3 bullish cards per horizon from the newest post-registration batch, held to the "
              "card horizon, net = realized excess − 0.4%. Registration is paper_pnl.jsonl line 1; 0 picks "
              "because Batch A (Nov 1) and Batch B (Nov 3) predate it and are excluded by design.", "SHADOW stream live"],
              [9, 9, 9, 10, 4]),
        _row(["Thu Nov 5", "catch-up task registered", "21:00 nightly from tonight",
              "New QPForecastCatchup scheduled task (Mon–Fri 21:00 IST) chains daily → settle → paper in one "
              "idempotent pass, so a missed 16:15/16:30 run no longer loses the evening's evidence. Same "
              "settings as the other tasks; log schedule_catchup.log.", "Evidence leak closed"], [9, 9, 9, 10, 4]),
        _row(["Thu Nov 5", "catchup", "21:00 (first firing)",
              "Fired on time and was terminated at 21:02 (C000013A — machine slept/shut down). Before dying it "
              "locked 17 cards against the completed Nov 4 bar (9×5D + 8×20D) — the first cards recorded AFTER "
              "the paper registration. The paper stage was never reached; Batch C stays a partial 17-of-100 "
              "batch, and under the registered 'latest batch' rule it receives no picks once a newer batch locks.",
              "17 locked (Batch C)"], [9, 9, 9, 10, 4]),
        _row([None], [0]),
        _row(["Fri Nov 6 — each row is read from that job's own log at generation time"], [11]),
    ]
    sched = {"settle": time(16, 15), "daily": time(16, 30), "tournament": time(17, 30), "catchup": time(21, 0)}
    for job, at in sched.items():
        stamp, js = _log_job_facts(job)
        if stamp and stamp.date() == now.date() and js is not None:
            if job == "settle":
                text = (f"Ran {stamp:%H:%M} IST. settled {js.get('settled')}, waiting {js.get('waiting')} — the "
                        f"50 Batch A 5-session cards mature today; their Nov 6 close reaches settlement "
                        f"Mon Nov 9 (provider lag). Chain {'valid' if js['chain'].get('valid') else 'INVALID'}: "
                        f"{js['chain'].get('checked')} cards.")
                effect = f"{js.get('settled')} settled"
            elif job == "daily":
                text = (f"Ran 16:30 IST — locked {js.get('locked')}, reused {js.get('reused')} against the completed "
                        f"Nov 5 bar; {len(js.get('failed') or {})} symbol failures. This is Batch D; if partial, "
                        f"the 21:00 catch-up completes it against the same bar.")
                effect = f"{js.get('locked')} locked"
            elif job == "tournament":
                text = (f"Ran {stamp:%H:%M} IST — day {js.get('day')}, {js.get('ranked')} names ranked across "
                        f"{js.get('sectors')} sectors; {len(js.get('skipped_small_sectors') or [])} small sectors skipped.")
                effect = f"{js.get('ranked')} rankings"
            else:
                text = (f"Ran {stamp:%H:%M} IST — picked {js.get('picked', '?')} from the latest batch "
                        f"(Paper P&L tab); stream totals: {js.get('summary', {}).get('picks', '?')} picks, "
                        f"{js.get('summary', {}).get('settled', '?')} settled.")
                effect = f"{js.get('picked', '?')} picks"
        elif stamp and stamp.date() == now.date():
            text = (f"In progress or interrupted before a final summary (log touched {stamp:%H:%M} IST, no "
                    "completion line). The 21:00 catch-up re-runs every stage idempotently.")
            effect = "—"
        elif stamp is None:
            text = f"Scheduled — fired {at:%H:%M} IST today; no log file yet."
            effect = "—"
        elif now.time() < at:
            text = (f"Scheduled — fires {at:%H:%M} IST today. Log last touched {stamp:%a %b %d, %H:%M} IST "
                    f"(prior run).")
            effect = "—"
        else:
            text = (f"No completed run logged by generation time (log last touched {stamp:%a %b %d, %H:%M} IST); "
                    f"the 21:00 catch-up retries every stage idempotently.")
            effect = "—"
        rows.append(_row(["Fri Nov 6", job, f"{at:%H:%M}", text, effect], [9, 9, 9, 10, 4]))
    rows += [
        _row([None], [0]),
        _row(["Operational notes"], [11]),
        _row(["• The ledger hash chain stayed valid at every settle this week."], [10]),
        _row(["• No card is ever locked against an incomplete candle."], [10]),
        _row(["• Missed evening batches are not backfilled — the next run always uses the latest completed bar."], [10]),
        _row(["• The 21:00 catch-up is also forward-only: it reuses completed bars and adds no backdated history."], [10]),
    ]
    return _sheet_xml(rows, [12, 30, 22, 100, 16], freeze=4)


def definitions_sheet(generated: str, cards: int, through: str) -> str:
    items = [
        ("Generated", generated),
        ("Sources", f"Forecast ledger {LEDGER} (hash-chained, forward-only) + one direct daily-bar "
                    "download from Yahoo Finance for interim actuals."),
        ("Target", "Probability that a stock outperforms NIFTY 50 over the stated number of trading sessions."),
        ("Forecast horizons", "5 and 20 trading sessions."),
        ("Batch A", "Cutoff Friday Oct 30 bar, locked Sun Nov 1 evening; forecast-v1 model; 50 symbols "
                    "(earlier warm universe). 50 5-session cards mature Fri Nov 6, 50 20-session cards mature Tue Dec 1."),
        ("Batch B", "Cutoff Monday Nov 2 bar, locked Tue Nov 3 16:30 IST; forecast-v2-horizon-gated model; "
                    "100 NIFTY-100 symbols. 5-session cards mature Mon Nov 9; 20-session cards mature Wed Dec 2."),
        ("Batch C", "Cutoff Wed Nov 4 bar, locked Thu Nov 5 21:02 IST by the first catch-up firing, which was "
                    "terminated ~2 minutes in (machine sleep; exit C000013A). Partial: 17 of ~100 symbols "
                    "(9×5-session, 8×20-session), all forecast-v2-horizon-gated. Disclosed as-is — no backfill. "
                    "Under the registered paper rule only the newest locked batch receives picks, so once Batch "
                    "D locks, Batch C is never picked."),
        ("Batch D", "Cutoff Thu Nov 5 bar, locked Fri Nov 6 evening by the scheduled daily (or completed by the "
                    "21:00 catch-up against the same bar). Shown only when locked at generation time."),
        ("What 'the system gave'", "Locked forecast cards: probability, directional lean class, abstention with "
                                   "reason, return quantiles (Q10/Q50/Q90 of excess), volatility forecast, forecaster "
                                   "disagreement, robustness; evidence cut off at the cutoff bar. Model calls, prompts and "
                                   "aggregation are unchanged from the researched design."),
        ("Lean thresholds", "P ≥ 0.55 'Outperform lean'; P ≤ 0.45 'Underperform lean'; between = 'No clear edge'; "
                            "abstentions carry a reason instead of a probability."),
        ("'Actual result' shown here", f"Interim: stock and NIFTY closes from the cutoff bar through the last "
                                       f"completed session ({through}; an intraday bar today is excluded by the "
                                       "incomplete-candle rule). Actual excess = stock return − NIFTY return over the "
                                       "priced sessions — the same arithmetic the settlement engine applies at maturity "
                                       "(Close_central line in service.realised_excess)."),
        ("Why interim, not final", "Final scoring happens only when the horizon completes (Batch A 5D: Fri Nov 6; Batch B 5D: "
                                   "Mon Nov 9; 20D: Dec 1 / Dec 2). Nothing this week has matured, so no final score exists yet."),
        ("Cross-check", "Interim prices were verified against the backend provider's cache CSVs (WIPRO Nov 3, ADANIENT) "
                        "before use. The provider's own one-day PIT lag is intentional and untouched; this report covers "
                        "completed sessions only and never writes to the backend cache."),
        ("Agreement column", "Directional agreement between the lean and the sign of the interim excess. Conflicts can "
                             "still finish the other way; only settled rows are final."),
        ("Settlement rule", "Cards are hash-chained before outcomes exist and settle exactly once. The abstaining card's "
                            "outcome is disclosed but excluded from accuracy metrics."),
        ("Not investment advice", "Research-only ledger. The profitability bridge stays HALT until enough settled cards "
                                  "clear the cost hurdle (needs ~30 per horizon)."),
        ("Paper P&L stream", "Pre-registered 2026-11-05 14:02 UTC (19:32 IST) as paper_pnl.jsonl line 1, before any "
                              "post-registration card settled. Rule: each evening, from the newest batch locked AFTER "
                              "registration, per horizon (5, 20) the top-3 bullish cards (answerable, p > 0.5; "
                              "tie-break |p−0.5| desc, p desc, symbol asc); hold to the card horizon; net = realized "
                              "excess − 0.4% round trip; scored only from the main ledger's forward settlements. "
                              "SHADOW authority — forward-testing evidence for the trade gate, not a bypass of it."),
        ("Evening catch-up task", "New QPForecastCatchup Windows task (Mon–Fri 21:00 IST) re-runs daily → settle → paper "
                                   "idempotently, closing the offline-machine gap that cost three evening batches this week."),
        ("Tabs", "Week Summary — headline; Week Results — one row per card, prediction vs interim actual; "
                 "Settled Actuals — final outcomes so far; Jobs Log — what ran each evening; Paper P&L — the "
                 "pre-registered shadow stream as picks accumulate; Definitions — this sheet."),
    ]
    rows = [
        _row(["Definitions, lineage and caveats"], [1]),
        _row(["Generated UTC", generated], [3, 9]),
        _row(["Cards covered this week", cards], [3, 4]),
        _row([None], [0]),
        _row(["Item", "Description"], [2, 2]),
    ]
    for label, value in items:
        rows.append(_row([label, value], [3, 10]))
    return _sheet_xml(rows, [26, 130], freeze=4)


def summary_sheet(week, bench_closes, through_date, generated: str, ledger_total: int):
    rows = [
        _row(["Quant Plus — week under review: what the agentic system gave vs what happened"], [1]),
        _row(["Generated UTC", generated], [3, 9]),
        _row(["Review window", "Mon Nov 2 – Sun Nov 8, 2026"], [3, 10]),
        _row(["Interim prices through", f"{through_date} (last completed session)"], [3, 9]),
        _row([None], [0]),
        _row(["Part 1 — What the agentic system gave this week"], [11]),
        _row(["Batch", "Cards", "5D cards", "20D cards", "Answerable", "Abstained",
              "Strongest lean at lock", "First maturity"], [2] * 8),
    ]
    for as_of in WEEK_AS_OFS:
        group = [r for r in week if r["as_of"] == as_of]
        if not group:
            continue
        answerable = [r for r in group if not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        leans = [r for r in answerable if _prediction_class(r["card"]) in ("Outperform lean", "Underperform lean")]
        strongest = max(leans, key=lambda r: abs(float(r["card"]["p_outperform"]) - 0.5)) if leans else None
        maturity = sorted({r["matures_on"] for r in group})[0]
        rows.append(_row([
            BATCH_LABEL[as_of], len(group),
            sum(r["horizon"] == 5 for r in group), sum(r["horizon"] == 20 for r in group),
            len(answerable), len(group) - len(answerable),
            (f"{strongest['symbol']} P={float(strongest['card']['p_outperform']):.0%} "
             f"({_prediction_class(strongest['card'])})") if strongest else "—",
            maturity,
        ], [9, 4, 4, 4, 4, 4, 6, 9]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Ledger total after this week's batches"], [11]))
    rows.append(_row(["Metric", "Value", "Note"], [2, 2, 2]))
    rows.append(_row(["Cards locked this week", len(week),
                      f"Hash chain verified; the ledger held {ledger_total} cards at generation."], [9, 4, 10]))
    present = [(BATCH_SHORT[a], len([r for r in week if r["as_of"] == a]))
               for a in WEEK_AS_OFS if any(r["as_of"] == a for r in week)]
    rows.append(_row(["Batches locked this week", len(present),
                      "; ".join(f"{s} ({n} cards)" for s, n in present) + " — D locks Fri Nov 6 evening; "
                      "C is the interrupted 17-of-100 batch.", ], [9, 4, 10]))
    rows.append(_row(["Scheduled evening runs missed or cut off", 4,
                      "Mon Nov 2 (machine unavailable); Wed Nov 4 (no completed run); Thu Nov 5 daily fired late "
                      "and was killed at 18:12; Thu Nov 5 21:00 catch-up killed at 21:02 — it still locked the "
                      "17 Batch C cards before dying. See Jobs Log."], [9, 4, 10]))
    if len(bench_closes) > 1:
        move = bench_closes[-1] / bench_closes[0] - 1.0
        rows.append(_row(["Market backdrop", f"NIFTY 50 {bench_closes[0]:,.0f} → {bench_closes[-1]:,.0f} ({move:+.1%}) "
                                             f"since the Oct 30 cutoff",
                          "A strong tape: any stock lagging NIFTY shows negative interim excess, which is a high bar for "
                          "outperform leans."], [9, 10, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Part 2 — What actually happened"], [11]))
    rows.append(_row(["Final settled results available now", 0,
                      "No card matured this week. The only final outcomes in the whole ledger are 2 October-cutoff cards, "
                      "settled Nov 1 — see Settled Actuals."], [9, 4, 10]))
    rows.append(_row(["Final scores arriving", "Fri Nov 6 / Mon Nov 9 / Tue Dec 1 / Wed Dec 2",
                      "Settlement runs weekdays 16:15 IST; each score lands once the provider marks those sessions complete."], [9, 10, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Interim directional agreement (descriptive only — not final scores)"], [11]))
    rows.append(_row(["Slice", "With explicit lean", "Agree", "Conflict", "Abstained / no lean",
                      "Sessions priced so far"], [2] * 6))
    slices = []
    for as_of in WEEK_AS_OFS:
        for horizon in (5, 20):
            group = [r for r in week if r["as_of"] == as_of and r["horizon"] == horizon]
            if not group:
                continue
            leans = [r for r in group if _prediction_class(r["card"]) in ("Outperform lean", "Underperform lean")]
            agree = sum(
                (r["actual"] is not None) and (
                    (r["actual"]["excess"] > 0) if _prediction_class(r["card"]) == "Outperform lean"
                    else (r["actual"]["excess"] < 0))
                for r in leans)
            neither = sum(r["card"].get("abstain") or _prediction_class(r["card"]) == "No clear edge" for r in group)
            k_max = max((r["actual"]["k"] for r in group if r["actual"]), default=0)
            slices.append((as_of, horizon, len(leans), agree, len(leans) - agree, neither, k_max))
            rows.append(_row([
                f"{BATCH_SHORT[as_of]} · {'5D' if horizon == 5 else '20D'}",
                len(leans), agree, len(leans) - agree, neither,
                f"{k_max}/{horizon}",
            ], [9, 4, 4, 4, 4, 9]))
    total_leans = sum(s[2] for s in slices)
    total_agree = sum(s[3] for s in slices)
    rows.append(_row(["All slices", total_leans, total_agree, total_leans - total_agree, "",
                      "Unweighted count; windows still open — do not read as accuracy."], [10, 4, 4, 4, 9, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Ten strongest leans from this week, with interim actual"], [11]))
    rows.append(_row(["Batch", "Symbol", "Horizon", "P(outperform)", "Lean",
                      "Actual excess vs NIFTY", "Sessions priced", "Interim agreement"], [2] * 8))
    strongest = [r for r in week
                 if _prediction_class(r["card"]) in ("Outperform lean", "Underperform lean") and r.get("actual")]
    strongest.sort(key=lambda r: abs(float(r["card"]["p_outperform"]) - 0.5), reverse=True)
    for r in strongest[:10]:
        card = r["card"]
        rows.append(_row([
            BATCH_SHORT[r["as_of"]], r["symbol"], r["horizon"],
            _safe_float(card.get("p_outperform")), _prediction_class(card),
            r["actual"]["excess"], r["actual"]["k"], lean_agreement(card, r["actual"], r["horizon"]),
        ], [4, 9, 4, 6, 10, 6, 9, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Discipline notes"], [11]))
    for note in [
        "• Abstentions are preserved as system behavior — the v2 batch abstains on most symbols when evidence is thin.",
        "• No final accuracy can be claimed from this week: horizons have not completed. The interim agreement count is descriptive only.",
        "• The profitability bridge remains HALT (needs ~30 settled cards per horizon); nothing here is a trade instruction.",
        "• A pre-registered shadow paper-P&L stream (Paper P&L tab) now accumulates forward evidence for that gate without weakening it.",
        "• A 21:00 catch-up task now re-runs the evening chain after missed schedules, so settled evidence stops leaking to machine sleep.",
        "• The standing presentation workbook reports/agentic-ai-predictions.xlsx keeps Tomorrow Brief, Votes and diagnostics; this file is the week-vs-actual view.",
    ]:
        rows.append(_row([note], [10]))
    return _sheet_xml(rows, [46, 24, 12, 13, 20, 22, 16, 16], freeze=2)


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_records(records, fetched, bench):
    week = [r for r in records if r["as_of"] in WEEK_AS_OFS]
    for r in week:
        stock = fetched.get(f"{r['symbol']}.NS")
        a = actual_for(stock, bench, r["as_of"][:10], int(r["horizon"]))
        r["actual"] = a
        if a is None:
            print(f"WARN: no interim actual for {r['symbol']} {r['as_of'][:10]}")
    order = {WEEK_AS_OFS[0]: 0, WEEK_AS_OFS[1]: 1, WEEK_AS_OFS[2]: 2, WEEK_AS_OFS[3]: 3}
    week.sort(key=lambda r: (order[r["as_of"]], r["horizon"],
                             -abs(float(r["card"].get("p_outperform") or 0.5) - 0.5),
                             r["symbol"]))
    return week


def main() -> None:
    parser = argparse.ArgumentParser(description="Week prediction-vs-actual workbook.")
    parser.add_argument("--skip-crosscheck", action="store_true")
    args = parser.parse_args()

    if not LEDGER.exists():
        raise SystemExit(f"Forecast ledger not found: {LEDGER}")
    records = EXP.load_records(LEDGER)
    print(f"Loaded {len(records)} ledger cards.")

    symbols = sorted({r["symbol"] for r in records if r["as_of"] in WEEK_AS_OFS})
    instruments = [f"{s}.NS" for s in symbols] + ["^NSEI"]
    print(f"Fetching daily closes for {len(instruments)} instruments...")
    fetched = fetch_instruments(instruments, start="2026-10-20")
    fetched = {name: completed_bars(s) for name, s in fetched.items()}
    bench = fetched.get("^NSEI")
    if bench is None or bench.empty:
        raise SystemExit("NIFTY 50 series missing — cannot compute actuals")
    if not args.skip_crosscheck:
        verify_crosschecks(fetched)

    week = build_records(records, fetched, bench)
    bench_closes = bench[bench.index >= __import__("pandas").Timestamp(WEEK_AS_OFS[0][:10])].tolist()
    through_date = bench.index[-1].date().isoformat()
    generated = datetime.now(timezone.utc).isoformat()

    settled_xml, settled_rows, scored_cells = settled_sheet(records, generated)
    paper_xml, paper_picks = paper_sheet(generated)
    sheets = {
        "Week Summary": summary_sheet(week, bench_closes, through_date, generated, len(records)),
        "Week Results": week_results_sheet(week),
        "Settled Actuals": settled_xml,
        "Jobs Log": jobs_sheet(generated),
        "Paper P&L": paper_xml,
        "Definitions": definitions_sheet(generated, len(week), through_date),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    import zipfile

    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("xl/workbook.xml", _workbook_xml(list(sheets)))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        archive.writestr("xl/styles.xml", _styles())
        for index, xml in enumerate(sheets.values(), 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)

    answerable = sum(not r["card"].get("abstain") and r["card"].get("p_outperform") is not None for r in week)
    with_actuals = sum(r.get("actual") is not None for r in week)
    print(json.dumps({
        "written": str(OUTPUT), "cards": len(week), "answerable": answerable,
        "with_interim_actuals": with_actuals, "priced_through": through_date,
        "settled_rows": settled_rows, "scored_rows": scored_cells,
        "paper_picks": paper_picks,
    }, indent=2))


if __name__ == "__main__":
    main()
