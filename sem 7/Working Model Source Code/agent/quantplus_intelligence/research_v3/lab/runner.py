"""W2 deterministic research runner: run_backtest / run_sweep / holdout seal.

Engine semantics (all preregistered in the spec, none implicit):

- decisions: 00:15 IST on each rebalance period's first *observed* session —
  sees only bars with ``available_at <= decision_ts``;
- eligibility: as-of member (mode-dependent weak-row disclosure) + trades on
  the entry session + computable signal (typed abstention on corrupted or
  short lookbacks);
- fills: top-k equal weight at the entry session OPEN, exit at the NEXT
  rebalance's execution OPEN (W1 boundary fix — the chain rolls execution
  price to execution price, no overnight move silently dropped);
- verified corporate actions inside a holding are cash-consistent: sell
  turnover = qty x exit_raw x (cum_entry/cum_exit) with cumulative VERIFIED
  factors only; unverified actions stay raw + disclosed (never imputed);
- fees: the exact W0 paper-book model (economics.trade_cash_pnl) on slipped
  turnover; slippage is an adverse integer-paise price adjustment scenario;
- NAV: every fill lands in the ledger; net NAV reconciles from fills, never
  from a performance shortcut; broken (missing-month) chains are reported as
  segments and the whole-window continuous NAV is withheld with a cause.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

from quantplus_intelligence.research_v3 import economics as E
from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab import data as D
from quantplus_intelligence.research_v3.lab.spec import (
    BacktestResult, SpecError, StrategySpec, SweepResult, fingerprint)

MAX_GRID_CARDINALITY = 64
MAX_MONTHS_PER_RUN = 200
DECISION_TIME = "T00:15:00+05:30"
# Sweep overrides are allowlisted (bounded, typed): anything else must be a
# new preregistered spec version, never an ad-hoc grid axis.
_VARIANT_FIELDS = frozenset({
    "lookback_sessions", "skip_sessions", "top_k", "high_window_sessions",
    "min_history_sessions", "slippage_bps"})


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _slip_adverse(price_paise: int, bps: int, side: str) -> int:
    """Adverse integer-paise execution adjustment (buyer pays more, seller gets less)."""
    if bps == 0:
        return price_paise
    if side == "BUY":
        return math.ceil(price_paise * (1 + bps / 10_000))
    return math.floor(price_paise * (1 - bps / 10_000))


def _period_first_sessions(panel: D.PitPanel, rebalance: str):
    """[(period_key, first_session)] — calendar months ('YYYY-MM') or quarters
    ('YYYY-Qn')."""
    out, seen = [], set()
    step = 3 if rebalance == "quarterly" else 1
    for s in panel.sessions:
        if rebalance == "quarterly":
            key = f"{s[:4]}-Q{(int(s[5:7]) - 1) // 3 + 1}"
        else:
            key = s[:7]
        if key not in seen:
            seen.add(key)
            out.append((key, s))
    return out


def _cash_acct(qty, buy_paise, sell_paise, buy_session, sell_session, broker):
    """Exact paper-book accounting; typed gross-only before the fee effective date."""
    try:
        acct = E.trade_cash_pnl(qty, buy_paise, sell_paise,
                                buy_session + "T00:00:00+05:30",
                                sell_session + "T00:00:00+05:30", broker=broker)
        return acct, "OK"
    except ValueError as exc:
        if str(exc) != E.ScheduleUnavailable:
            raise
        return None, "SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE"


def _exec_info(panel: D.PitPanel, conn, sym: str, F: str, F_next: str,
               bps: int) -> dict | None:
    """Execution record for one name in one period (strategy and placebo share it).

    Entry: the F-session open, slipped adverse. Exit: the F_next-session open
    (W1 boundary rule), or the next executable open within 5 sessions when the
    name does not trade on F_next (extension disclosed per fill).

    Verified-action cash consistency: when the warehouse holds VERIFIED factors
    at both ends, the sell price is restated to the entry share basis
    (``sell_eff = sell_raw x cum_entry / cum_exit``; price-ratio factor
    convention — a 2:1 split carries factor 0.5) so the round trip earns the
    holder's true economics. Unverified actions stay RAW + disclosed.
    """
    eb = panel.bar_on(sym, F)
    if eb is None or eb[0] <= 0:
        return None
    x = panel.bar_on(sym, F_next)
    if x is None or x[0] <= 0:
        ext = _next_open(panel, sym, F_next, 5)
        if ext is None:
            return None
        exit_session, exit_open, extended = ext[0], ext[1], True
    else:
        exit_session, exit_open, extended = F_next, x[0], False
    buy_p = _slip_adverse(eb[0], bps, "BUY")
    sell_p = _slip_adverse(exit_open, bps, "SELL")
    if buy_p <= 0:
        return None
    cum_e, st_e = W.adjustment_factor(conn, sym, F)
    cum_x, st_x = W.adjustment_factor(conn, sym, exit_session)
    verified = st_e == "VERIFIED" and st_x == "VERIFIED"
    basis = "ADJUSTED_VERIFIED" if verified and (cum_e != 1.0 or cum_x != 1.0) \
        else "RAW_UNADJUSTED"
    sell_eff = math.floor(sell_p * cum_e / cum_x) if verified and cum_x > 0 else sell_p
    return {
        "entry_session": F, "entry_open_paise": eb[0], "buy_paise": buy_p,
        "exit_session": exit_session, "exit_open_paise": exit_open,
        "sell_paise": sell_eff, "exit_extended": extended,
        "adjustment_basis": basis,
        "gross_return": (sell_eff / buy_p - 1) if buy_p else None,
    }


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------

def run_backtest(spec: StrategySpec, *, phase: str = "train_validation",
                 conn: sqlite3.Connection | None = None,
                 panel: D.PitPanel | None = None) -> BacktestResult:
    """Deterministic, cost-inclusive backtest of one StrategySpec phase.

    ``phase`` is train_validation (default; sweeps) or holdout (explicit final
    evaluation only — see journal.seal/reveal discipline).
    """
    if conn is None:
        conn = W.connect(W.DEFAULT_DB)
    if phase not in ("train_validation", "holdout", "train", "validation"):
        raise SpecError(f"unknown phase {phase!r}")
    start, end = spec.windows.phase_bounds(phase)
    panel = panel or D.PitPanel(conn, spec.universe.universe_id)

    periods = _period_first_sessions(panel, spec.execution.rebalance)
    # entry periods strictly inside [start, end]; the exit is the NEXT period's
    # first session — an entry whose next period starts after `end` is unlabelled
    idx0 = next((i for i, (_k, s) in enumerate(periods) if s >= start), None)
    if idx0 is None:
        raise SpecError(f"no observed session at/after {start} in the warehouse")
    if len(periods) - idx0 < 2:
        raise SpecError(f"window {start}..{end} holds fewer than 2 rebalance periods")

    months, fills, abstained = [], [], []
    n = len(periods)
    i = idx0
    while i < n - 1:
        key, F = periods[i]
        F_next = periods[i + 1][1]
        if F_next > end:
            # label would mature beyond the phase boundary: censor it (no
            # partial label, no fold crossing) — purge/embargo by construction
            break
        decision_ts = F + DECISION_TIME
        mem = panel.members_at(decision_ts, spec.universe.membership_mode)
        if mem.status == "UNKNOWN":
            abstained.append({"period": key, "cause": "MEMBERSHIP_UNKNOWN",
                              "entry_session": F})
            i += 1
            continue
        eligible = []
        for mem_sym in mem.rows:
            sym = panel.key_for(mem_sym)
            if sym is None:
                continue          # no bar history for this member: disclosed miss
            if spec.universe.require_entry_session_bar and panel.bar_on(sym, F) is None:
                continue
            sig = _signal(panel, spec, sym, decision_ts)
            if sig is None:
                continue
            eligible.append((sym, sig))
        eligible.sort(key=lambda t: (-t[1], t[0]))     # deterministic tie-break
        # Execution info for EVERY eligible name: the placebo's matched-noise
        # pool must be the whole eligible set (not only the chosen names), and
        # per-name gross must follow the SAME execution rule as the strategy.
        infos: dict[str, dict | None] = {sym: _exec_info(panel, conn, sym, F,
                                                         F_next,
                                                         spec.execution.slippage_bps)
                                         for sym, _sig in eligible}
        eligible_symbols = [sym for sym, _sig in eligible]
        eligible_gross = {s: v["gross_return"] for s, v in infos.items() if v}
        chosen = eligible[:spec.signal.top_k]
        if not chosen:
            abstained.append({"period": key, "cause": "NO_ELIGIBLE_SIGNALS",
                              "entry_session": F, "n_members": len(mem.rows),
                              "n_signal_abstained": len(mem.rows) - len(eligible)})
            i += 1
            continue
        if not eligible_gross:
            abstained.append({"period": key, "cause": "NO_EXECUTABLE_FILLS",
                              "entry_session": F, "n_eligible": len(eligible)})
            i += 1
            continue

        per_name = spec.execution.capital_paise // len(chosen)
        rows, ok = [], []
        for rank, (sym, _sig) in enumerate(chosen, start=1):
            e = infos[sym]
            if e is None:
                continue          # unfillable (no executable exit): disclosed, never guessed
            qty = per_name // e["buy_paise"]
            if qty <= 0:
                continue
            acct, charges_status = _cash_acct(qty, e["buy_paise"], e["sell_paise"],
                                              F, e["exit_session"],
                                              spec.execution.broker)
            disc = panel.holding_discontinuities(sym, F, e["exit_session"])
            fill = {
                "period": key, "symbol": sym,
                "entry_session": F, "entry_open_paise": e["entry_open_paise"],
                "buy_paise": e["buy_paise"],
                "exit_session": e["exit_session"],
                "exit_open_paise": e["exit_open_paise"],
                "sell_paise": e["sell_paise"], "exit_extended": e["exit_extended"],
                "quantity": qty, "charges_status": charges_status,
                "accounting": acct,
                "gross_return": e["gross_return"],
                "adjustment_basis": e["adjustment_basis"],
                "action_discontinuities": disc,
                "signal_rank": rank,
            }
            fills.append(fill)
            rows.append(fill)
            if acct is not None:
                ok.append(fill)
        gross_month = (sum(f["gross_return"] for f in rows) / len(rows)) if rows else None
        net_month = (sum(f["accounting"]["v3_net_absolute"] for f in ok) / len(ok)) \
            if ok else None
        months.append({
            "period": key, "decision_ts": decision_ts,
            "entry_session": F, "exit_session": F_next,
            "membership_status": mem.status,
            "weak_rows_included": mem.meta.get("weak_rows_included"),
            "n_members": len(mem.rows), "n_eligible": len(eligible),
            "n_fillable": len(eligible_gross),
            "n_chosen": len(chosen), "n_fills": len(rows),
            "eligible_symbols": eligible_symbols,
            "eligible_gross": eligible_gross,
            "gross_month": gross_month, "net_month": net_month,
            "charges_status": "OK" if ok and len(ok) == len(rows)
                              else ("MIXED" if ok else "SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE"),
            "n_action_discontinuity_fills": sum(1 for f in rows
                                                if f["action_discontinuities"]),
        })
        i += 1

    result = _assemble_result(spec, phase, months, fills, abstained, panel, conn)
    return result


def _signal(panel: D.PitPanel, spec: StrategySpec, sym: str, decision_ts: str):
    fam = spec.signal.family
    if fam == "cross_sectional_momentum":
        return panel.momentum(sym, decision_ts, spec.signal.lookback_sessions,
                              spec.signal.skip_sessions,
                              spec.signal.min_history_sessions)
    if fam == "near_52w_high":
        return panel.near_52w_high(sym, decision_ts,
                                   spec.signal.high_window_sessions)
    if fam == "noise_control":
        import random
        # string seed -> deterministic across processes (hash() of str is salted)
        rng = random.Random(f"{spec.seed}|noise|{sym}|{decision_ts}")
        return rng.random()          # random rank, disclosed as a control
    if fam == "leak_control":
        # NEGATIVE CONTROL: ranks by the decision SESSION's close — a bar that
        # is NOT available at the decision. The runner executes it only because
        # the spec declared it; the challenger's availability audit FAILs it.
        return panel.bar_on(sym, panel.sessions[panel.pos[decision_ts[:10]]])[1] \
            if panel.bar_on(sym, decision_ts[:10]) else None
    raise SpecError(f"unhandled family {fam!r}")


def _next_open(panel: D.PitPanel, sym: str, session: str, max_wait: int):
    i = panel.pos[session]
    rows = panel.series.get(sym, ())
    by = {r[0]: r for r in rows}
    for s in panel.sessions[i:i + max_wait]:
        r = by.get(s)
        if r and r[1] > 0:
            return s, r[1]
    return None


def _assemble_result(spec: StrategySpec, phase: str, months, fills, abstained,
                     panel: D.PitPanel, conn) -> BacktestResult:
    labeled = [m for m in months if m["gross_month"] is not None]
    # contiguous labeled segments (calendar months; quarterly keys handled too)
    segments, cur = [], []
    prev = None
    for m in labeled:
        k = m["period"]
        if prev is not None and not _period_adjacent(prev, k):
            segments.append(tuple(cur))
            cur = []
        cur.append(k)
        prev = k
    if cur:
        segments.append(tuple(cur))

    continuous_blocked = None
    if len(segments) != 1 or (abstained and labeled):
        if abstained and labeled:
            continuous_blocked = (
                f"chain broken by {len(abstained)} abstained period(s); "
                f"{len(segments)} labeled segment(s) reported, whole-window "
                "continuous NAV withheld (missing observations are NOT flat)")
        elif len(segments) != 1:
            continuous_blocked = f"chain broken into {len(segments)} labeled segments"

    # NAV: compounded over labeled segments only, per segment (never across breaks)
    nav_segments = []
    for seg in segments:
        seg_rows = [m for m in labeled if m["period"] in set(seg)]
        g = 1.0
        n = 1.0
        for m in seg_rows:
            g *= 1 + m["gross_month"]
            if m["net_month"] is not None:
                n *= 1 + m["net_month"]
        nav_segments.append({"start": seg[0], "end": seg[-1], "n_periods": len(seg),
                             "gross": g - 1.0,
                             "net": (n - 1.0) if all(m["net_month"] is not None
                                                     for m in seg_rows) else None})

    total_charges = sum(f["accounting"]["charges_total_paise"]
                        for f in fills if f["accounting"])
    n_disc = sum(1 for f in fills if f["action_discontinuities"])
    # A hold across a price discontinuity blocks historical economics ONLY when
    # the action is unverified: a VERIFIED factor restates the round trip to the
    # holder's true economics (cash-consistent), so it is disclosed, not blocked.
    blocked_disc = sum(1 for f in fills if f["action_discontinuities"]
                       and f["adjustment_basis"] != "ADJUSTED_VERIFIED")
    economics_blocked = blocked_disc > 0 or any(
        m.get("weak_rows_included") for m in months)

    # benchmark (official TRI) over the labeled span — basis-labelled, never cash
    bench = None
    if labeled:
        try:
            bench = W.benchmark_total_return(conn, "NIFTY50_TRI",
                                             labeled[0]["entry_session"],
                                             labeled[-1]["exit_session"])
        except ValueError:
            bench = None

    warnings = []
    if n_disc:
        warnings.append(
            f"{n_disc} fill(s) hold through corporate-action price discontinuities"
            + (f" ({n_disc - blocked_disc} restated with VERIFIED factors; "
               f"{blocked_disc} left RAW — economics vs TRI not interpretable)"
               if blocked_disc else
               " (all restated with VERIFIED factors — cash-consistent)"))
    if any(m.get("weak_rows_included") for m in months):
        warnings.append("membership includes snapshot_floor spells (PARTIAL upper bound)")
    if continuous_blocked:
        warnings.append(continuous_blocked)

    status = "DATA_BLOCKED" if economics_blocked else "RESEARCH"

    payload = {
        "spec": spec.to_payload(),
        "spec_fingerprint": spec.fingerprint(),
        "result_id": None,
        "phase": phase,
        "status": status,
        "months": tuple(months),
        "fills": tuple(fills),
        "abstained_months": tuple(abstained),
        "labeled_segments": tuple(segments),
        "continuous_chain_blocked": continuous_blocked,
        "nav": {"segments": nav_segments,
                "whole_window_continuous": None if continuous_blocked
                else (nav_segments[0] if nav_segments else None)},
            "returns": {
            "absolute_gross_segments": [{"segment": s["start"] + ".." + s["end"],
                                         "gross": s["gross"]} for s in nav_segments],
            "absolute_net_segments": [{"segment": s["start"] + ".." + s["end"],
                                       "net": s["net"]} for s in nav_segments],
            # Excess vs TRI is reported per segment ONLY as a labelled,
            # not-cash figure; with raw-price fills the economic comparison is
            # blocked at the source (basis mismatch), not silently computed.
            "benchmark_relative_excess_segments": [
                {"segment": s["start"] + ".." + s["end"],
                 "excess_vs_tri_labeled_not_cash":
                     "DATA_BLOCKED_BENCHMARK_BASIS_MISMATCH"
                 if any(f["adjustment_basis"] == "RAW_UNADJUSTED" for f in fills)
                 else None} for s in nav_segments],
        },
        "benchmark": {"index": bench["index"] if bench else None,
                      "basis": bench["basis"] if bench else None,
                      "window": [bench["start_session"], bench["end_session"]] if bench else None,
                      "total_return": bench["total_return"] if bench else None,
                      "basis_comparison_allowed":
                          not any(f["adjustment_basis"] == "RAW_UNADJUSTED" for f in fills)},
        "price_basis": {"execution_prices": "RAW_UNADJUSTED_OFFICIAL",
                        "verified_action_fills": sum(1 for f in fills
                                                     if f["adjustment_basis"] == "ADJUSTED_VERIFIED"),
                        "action_discontinuity_fills": n_disc,
                        "economics_vs_tri_blocked": bool(blocked_disc)},
        "costs": {"charges_total_paise": total_charges,
                  "slippage_bps": spec.execution.slippage_bps,
                  "fee_model": "paper_book_exact_v0"},
        "scenario_nets": {},   # filled by run_cost_scenarios
        "warnings": tuple(warnings),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_hashes": _source_hashes(),
    }
    # result_id = sha256 of the canonical payload minus the result's own
    # generated_at AND minus the embedded spec's registration-instant fields
    # (created_at / preregistration_hash). The spec's pinned rule set (core
    # fingerprint) stays in: re-registering the same rule set at a later
    # instant and rerunning must yield the SAME result_id (deterministic
    # identity), while the preregistration contract keeps its instant.
    _canon = {k: v for k, v in payload.items()
              if k not in ("result_id", "generated_at")}
    if isinstance(_canon.get("spec"), dict):
        _canon["spec"] = {k: v for k, v in _canon["spec"].items()
                          if k not in ("created_at", "preregistration_hash")}
    rid = fingerprint({"payload": _canon})
    payload["result_id"] = rid
    return BacktestResult.from_payload(payload)


def _period_adjacent(a: str, b: str) -> bool:
    """Adjacent period keys: months ('YYYY-MM' → next month) or quarters
    ('YYYY-Qn' → next quarter, Q4 rolls to next year's Q1)."""
    if len(a) == 7 and len(b) == 7:      # monthly
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
        return (yb == ya and mb == ma + 1) or (yb == ya + 1 and ma == 12 and mb == 1)
    ya, qa = a[:4], a[6:]                # quarterly
    yb, qb = b[:4], b[6:]
    return (yb == ya and int(qb) == int(qa) + 1) or \
           (yb == str(int(ya) + 1) and qa == "4" and qb == "1")


def _source_hashes() -> dict:
    from pathlib import Path
    import json
    rep = Path(__file__).resolve().parents[4] / "reports" / "alpha_v3_1" / "pit_source_integrity.json"
    if rep.exists():
        sources = json.loads(rep.read_text(encoding="utf-8")).get("sources", {})
        return {k: v.get("sha256") for k, v in sources.items() if isinstance(v, dict)}
    return {}


# ---------------------------------------------------------------------------
# cost scenarios: base (spec bps) and double-cost (2x bps, adverse, same model)
# ---------------------------------------------------------------------------

def run_cost_scenarios(spec: StrategySpec, conn, panel,
                       phase: str = "train_validation") -> dict:
    """base + double-cost scenario summaries (slippage doubled, fees exact)."""
    base = run_backtest(spec, phase=phase, conn=conn, panel=panel)
    if spec.execution.slippage_bps * 2 > 200:
        raise SpecError("double-cost scenario exceeds the slippage bound")
    dbl_spec = _with_slippage(spec, spec.execution.slippage_bps * 2)
    dbl = run_backtest(dbl_spec, phase=phase, conn=conn, panel=panel)

    def net_summary(res):
        labeled = [m for m in res.months if m["net_month"] is not None]
        if not labeled:
            return None
        n = 1.0
        for m in labeled:
            n *= 1 + m["net_month"]
        return {"n_net_months": len(labeled), "net_product": n - 1.0,
                "charges_paise": sum(f["accounting"]["charges_total_paise"]
                                     for f in res.fills if f["accounting"])}

    return {"base": net_summary(base), "double_cost": net_summary(dbl),
            "base_result_id": base.result_id, "double_result_id": dbl.result_id}


def _with_slippage(spec: StrategySpec, bps: int) -> StrategySpec:
    from dataclasses import replace
    ex = replace(spec.execution, slippage_bps=bps)
    return replace(spec, execution=ex)


# ---------------------------------------------------------------------------
# run_sweep (bounded, holdout-free)
# ---------------------------------------------------------------------------

def run_sweep(base: StrategySpec, grid: dict[str, list], *,
              conn=None, panel: D.PitPanel | None = None) -> SweepResult:
    """Enumerate a BOUNDED grid over train+validation only. The sealed holdout
    is structurally unreachable: every variant's windows are the base's
    train/validation bounds."""
    if conn is None:
        conn = W.connect(W.DEFAULT_DB)
    if not isinstance(grid, dict) or not grid:
        raise SpecError("grid must be a non-empty dict of param -> list")
    import itertools
    import math as _m
    keys = sorted(grid)
    if any(not isinstance(v, list) or not v for v in grid.values()):
        raise SpecError("grid values must be non-empty lists")
    unknown = [k for k in keys if k not in _VARIANT_FIELDS]
    if unknown:
        raise SpecError(f"grid fields outside the allowlist: {unknown}")
    n = 1
    for k in keys:
        n *= len(grid[k])
    if n > MAX_GRID_CARDINALITY:
        raise SpecError(f"grid cardinality {n} exceeds bound {MAX_GRID_CARDINALITY}")
    panel = panel or D.PitPanel(conn, base.universe.universe_id)
    variants = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        over = dict(zip(keys, combo))
        try:
            spec = _variant_spec(base, over)
            res = run_backtest(spec, phase="train_validation", conn=conn, panel=panel)
            labeled = [m for m in res.months if m["gross_month"] is not None]
            g = 1.0
            for m in labeled:
                g *= 1 + m["gross_month"]
            variants.append({"override": over, "ok": True,
                             "spec_id": spec.spec_id,
                             "spec_fingerprint": spec.fingerprint(),
                             "result_id": res.result_id,
                             "status": res.status,
                             "n_labeled": len(labeled),
                             "n_abstained": len(res.abstained_months),
                             "gross_product": g - 1.0 if labeled else None,
                             "mean_monthly_gross": (sum(m["gross_month"] for m in labeled)
                                                    / len(labeled)) if labeled else None,
                             "error": None})
        except (SpecError, ValueError) as exc:
            variants.append({"override": over, "ok": False, "spec_id": None,
                             "spec_fingerprint": None, "result_id": None,
                             "status": "FAILED", "n_labeled": None,
                             "n_abstained": None, "gross_product": None,
                             "mean_monthly_gross": None,
                             "error": str(exc)})
    good = [v for v in variants if v["ok"] and v["gross_product"] is not None]
    best = max(good, key=lambda v: v["gross_product"]) if good else None
    plateau = None
    if best is not None:
        neighbours = [v for v in good if v is not best and _adjacent_override(
            v["override"], best["override"], keys)]
        vals = sorted([v["gross_product"] for v in neighbours]) if neighbours else []
        plateau = {
            "best": best["override"],
            "best_gross_product": best["gross_product"],
            "n_neighbours": len(neighbours),
            "neighbour_median": (vals[len(vals) // 2] if vals else None),
            "note": "isolated peak when neighbour median is far below best; "
                    "a lucky single cell is a rejection signal (blueprint §7.4)",
        }
    return SweepResult(
        base_spec=base.to_payload(), grid={k: list(v) for k, v in grid.items()},
        variants=tuple(variants), n_trials=len(variants),
        n_failed=sum(1 for v in variants if not v["ok"]),
        surface_note="every attempted configuration is recorded; "
                     "see wave2_parameter_sweep.csv for the full surface",
        plateau=plateau,
        best_variant=fingerprint(best["override"]) if best else None,
        best_neighbour_median=(plateau or {}).get("neighbour_median"),
        used_holdout=False,
        generated_at=datetime.now(timezone.utc).isoformat())


def _variant_spec(base: StrategySpec, override: dict) -> StrategySpec:
    import dataclasses
    sig_over = {k: v for k, v in override.items()
                if k in _VARIANT_FIELDS and k != "slippage_bps"}
    ex_over = {k: v for k, v in override.items() if k == "slippage_bps"}
    sig = dataclasses.replace(base.signal, **sig_over) if sig_over else base.signal
    ex = dataclasses.replace(base.execution, **ex_over) if ex_over else base.execution
    spec = dataclasses.replace(base, signal=sig, execution=ex,
                               spec_id=base.spec_id + "." + fingerprint(override)[:8],
                               version=base.version)
    return spec


def compare_runs(a: BacktestResult, b: BacktestResult) -> dict:
    """Paired comparison of two results with identical windows/universe/execution.

    The paired config is enforced structurally: the spec cores must agree on
    everything except the signal fields — otherwise the runs are not comparable
    and a typed error is returned instead of a misleading table.
    """
    ignore = {"signal", "hypothesis", "notes", "spec_id", "created_at", "seed"}
    core_a = {k: v for k, v in a.spec.items() if k not in ignore}
    core_b = {k: v for k, v in b.spec.items() if k not in ignore}
    if core_a != core_b:
        differing = [k for k in core_a if core_a.get(k) != core_b.get(k)]
        return {"comparable": False,
                "reason": "specs differ outside the signal fields; not a paired "
                          "configuration",
                "differing_fields": sorted(differing)}
    ma = {m["period"]: m for m in a.months if m["gross_month"] is not None}
    mb = {m["period"]: m for m in b.months if m["gross_month"] is not None}
    common = sorted(set(ma) & set(mb))
    diffs = [ma[p]["gross_month"] - mb[p]["gross_month"] for p in common]
    if common:
        seg, cur = [], [common[0]]
        for prev, cur_p in zip(common, common[1:]):
            if not _period_adjacent(prev, cur_p):
                seg.append(tuple(cur))
                cur = []
            cur.append(cur_p)
        seg.append(tuple(cur))
    else:
        seg = []
    segments = []
    for s in seg:
        s_set = set(s)
        ga = gb = 1.0
        for p in s:
            ga *= 1 + ma[p]["gross_month"]
            gb *= 1 + mb[p]["gross_month"]
        segments.append({"segment": f"{s[0]}..{s[-1]}", "n_periods": len(s),
                         "gross_a": ga - 1.0, "gross_b": gb - 1.0,
                         "excess_a_minus_b": (ga - gb) / gb if gb else None})
    return {
        "comparable": True,
        "run_a": a.result_id, "run_b": b.result_id,
        "spec_a": a.spec["spec_id"], "spec_b": b.spec["spec_id"],
        "n_common_periods": len(common),
        "n_only_a": len(set(ma) - set(mb)), "n_only_b": len(set(mb) - set(ma)),
        "mean_monthly_excess": (sum(diffs) / len(diffs)) if diffs else None,
        "segments": segments,
        "note": "paired gross returns on identical windows/universe/execution; "
                "excess is a labelled not-cash comparison",
    }


def _adjacent_override(a: dict, b: dict, keys: list[str]) -> bool:
    diff = [k for k in keys if a.get(k) != b.get(k)]
    return len(diff) == 1
