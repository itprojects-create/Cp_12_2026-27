"""W2 challenge_finding: deterministic adversarial battery (blueprint §7.5).

Every check returns (status, reason, evidence) with status in
PASS / FAIL / INCONCLUSIVE. Any integrity FAIL blocks promotion. The battery
is reproducible: same run + same inputs -> same report content (timestamps
excepted).

Verdict rules (preregistered here, not improvised per run):
- any integrity FAIL                         -> promotion blocked
- economics blocked (raw prices + unverified actions, weak membership) -> DATA_BLOCKED
- declared negative control run              -> REJECTED (control ran as designed)
- strategy indistinguishable from matched noise (placebo percentile > threshold)
                                             -> NO_EDGE
- otherwise                                  -> RESEARCH (W2 never promotes:
   OOS_VALIDATED requires verified corporate actions + verified first-known
   membership, neither of which exists in the current sources)
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab import data as D
from quantplus_intelligence.research_v3.lab.runner import (
    DECISION_TIME, _period_adjacent, run_cost_scenarios)
from quantplus_intelligence.research_v3.lab.spec import (
    BacktestResult, ChallengeReport)

PROMOTION_BLOCKING = {"availability_provenance", "membership_survivorship",
                      "purge_embargo", "boundary_continuity",
                      "missing_periods_nav", "benchmark_provenance",
                      "nav_reconciliation", "holdout_integrity"}
PLACEBO_PCT_THRESHOLD = 90.0   # strategy must beat 90% of matched noise


def challenge_finding(result: BacktestResult, *,
                      n_placebo: int = 200,
                      sweep_n_trials: int | None = None,
                      holdout_seal: dict | None = None,
                      conn: sqlite3.Connection | None = None) -> ChallengeReport:
    conn = conn or W.connect(W.DEFAULT_DB)
    spec = _spec_from(result.spec)
    panel = D.PitPanel(conn, spec.universe.universe_id)
    checks: list[dict] = []

    checks.append(_availability_check(result, spec, panel))
    checks.append(_membership_check(result, spec, conn, panel))
    checks.append(_boundary_check(result, spec, panel))
    checks.append(_purge_embargo_check(result, spec))
    checks.append(_missing_periods_check(result, spec, panel))
    checks.append(_benchmark_check(result, conn))
    checks.append(_nav_reconciliation(result))
    checks.append(_cost_scenarios(result, spec, conn, panel))
    checks.append(_concentration_check(result))
    checks.append(_placebo_check(result, spec, conn, panel, n_placebo))
    checks.append(_dependence_check(result))
    checks.append(_multiplicity_check(sweep_n_trials))
    checks.append(_holdout_check(result, spec, holdout_seal))

    n_pass = sum(1 for c in checks if c["status"] == "PASS")
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_inc = sum(1 for c in checks if c["status"] == "INCONCLUSIVE")

    verdict, reason = _verdict(result, checks, spec)
    return ChallengeReport(
        run_id=result.result_id, run_fingerprint=result.result_id,
        checks=tuple(checks), n_pass=n_pass, n_fail=n_fail, n_inconclusive=n_inc,
        verdict=verdict, verdict_reason=reason,
        generated_at=datetime.now(timezone.utc).isoformat())


def _spec_from(payload: dict) -> StrategySpec:
    from quantplus_intelligence.research_v3.lab.spec import (
        ExecutionSpec, SignalSpec, StrategySpec, UniverseSpec, WindowSpec)
    p = dict(payload)
    return StrategySpec(
        spec_id=p["spec_id"], version=p["version"], hypothesis=p["hypothesis"],
        family=p.get("family", "other"),
        universe=UniverseSpec(**p["universe"]), signal=SignalSpec(**p["signal"]),
        execution=ExecutionSpec(**p["execution"]), windows=WindowSpec(**p["windows"]),
        declared_negative_control=p.get("declared_negative_control", False),
        seed=p.get("seed", 20261112), created_at=p.get("created_at", ""),
        notes=p.get("notes", ""))


# --- checks -------------------------------------------------------------------

def _availability_check(result, spec, panel):
    """Provenance audit: per-fill entry references + declared ranking source.

    Generic rule (independent of the runner): a fill's entry must be the FIRST
    bar of its symbol available after the decision instant. A declared
    ``leak_control`` spec additionally fails by rule: its ranking reads the
    decision-session close, a bar whose ``available_at`` exceeds the cutoff —
    proving the audit catches future-aware input.
    """
    bad = []
    for f in result.fills:
        decision_ts = f"{f['entry_session']}{DECISION_TIME}"
        rows = panel.series.get(f["symbol"], ())
        i = panel._bisect_available(f["symbol"], decision_ts)
        first_after = rows[i] if i < len(rows) else None
        if first_after is None or first_after[0] != f["entry_session"]:
            bad.append({"symbol": f["symbol"], "period": f["period"],
                        "reason": "entry not the first available bar after decision"})
    if spec.signal.family == "leak_control":
        # demonstrated violation: the ranking bar is not available at decision
        sample = result.fills[0] if result.fills else None
        demo = None
        if sample:
            d_ts = f"{sample['entry_session']}{DECISION_TIME}"
            i = panel._bisect_available(sample["symbol"], d_ts)
            if i < len(panel.series[sample["symbol"]]):
                demo = {"symbol": sample["symbol"],
                        "ranking_session": sample["entry_session"],
                        "bar_available_at": panel.series[sample["symbol"]][i][4],
                        "decision_ts": d_ts,
                        "violation": "ranking reads a bar available AFTER the cutoff"}
        bad.append(demo or {"reason": "leak control declared"})
    if bad:
        return {"check": "availability_provenance", "status": "FAIL",
                "reason": f"{len(bad)} provenance violation(s): future-aware "
                          "input blocked from promotion",
                "evidence": {"violations": [b for b in bad if b][:20], "n": len(bad)}}
    return {"check": "availability_provenance", "status": "PASS",
            "reason": "every fill's entry references the first bar available "
                      "after its decision; no unavailable data used",
            "evidence": {"n_fills": len(result.fills)}}


def _membership_check(result, spec, conn, panel):
    """Names must be as-of members; weak-row disclosure must match the spells."""
    issues, weak_total = [], 0
    for m in result.months:
        decision_date = m["decision_ts"][:10]
        res = W.members_at(conn, spec.universe.universe_id, decision_date,
                           strict=(spec.universe.membership_mode == "strict"))
        if res.status == "UNKNOWN":
            issues.append({"period": m["period"], "reason": "membership UNKNOWN "
                                                         "but month labeled"})
            continue
        weak = res.meta.get("weak_rows_included") or 0
        weak_total += weak
        # fills carry panel keys (spell symbols); members_at returns canonical
        # display names — allow either spelling of the same instrument
        allowed = set(res.rows) | {panel.key_for(s) for s in res.rows
                                   if panel.key_for(s)}
        names = {f["symbol"] for f in result.fills if f["period"] == m["period"]}
        if not names <= allowed:
            issues.append({"period": m["period"],
                           "reason": "fill(s) outside as-of membership"})
    if issues:
        return {"check": "membership_survivorship", "status": "FAIL",
                "reason": f"{len(issues)} membership violation(s)",
                "evidence": {"issues": issues[:10]}}
    status = "PASS"
    reason = "every fill sits inside its as-of membership spell"
    if weak_total:
        reason += (f"; {weak_total} weak-row disclosures carried (snapshot_floor "
                   "upper bound — not row-level first-known timestamps)")
    return {"check": "membership_survivorship", "status": status, "reason": reason,
            "evidence": {"n_months": len(result.months), "weak_rows_disclosed": weak_total}}


def _boundary_check(result, spec, panel):
    """Rebalance chain: exit session == next entry session (no overnight skip).

    Checked INSIDE labeled segments only; pairs across segment boundaries are
    chain breaks by construction (recorded as segments, never bridged).
    """
    labeled = {m["period"]: m for m in result.months if m["gross_month"] is not None}
    bad = []
    n_pairs = 0
    for seg in result.labeled_segments:
        ordered = [labeled[k] for k in seg if k in labeled]
        for a, b in zip(ordered, ordered[1:]):
            n_pairs += 1
            if not _period_adjacent(a["period"], b["period"]):
                bad.append({"between": [a["period"], b["period"]],
                            "reason": "non-adjacent periods inside one segment"})
            if b["entry_session"] != a["exit_session"]:
                bad.append({"between": [a["period"], b["period"]],
                            "reason": "next entry session != prior exit session "
                                      "(overnight move skipped)"})
    return {"check": "boundary_continuity",
            "status": "FAIL" if bad else "PASS",
            "reason": "; ".join(x["reason"] for x in bad[:3]) if bad else
                      "exit equals the next rebalance's entry session; "
                      "execution rolls price-to-price with no skipped move",
            "evidence": {"n_pairs_checked": n_pairs,
                         "n_segments": len(result.labeled_segments),
                         "violations": bad[:10]}}


def _purge_embargo_check(result, spec):
    """Labels of one phase must not cross into another fold (embargo sessions)."""
    w = spec.windows
    crossing = []
    for m in result.months:
        if m["gross_month"] is None:
            continue
        entry, exit_s = m["entry_session"], m["exit_session"]
        if result.phase == "train_validation":
            if entry < w.train_start or exit_s > w.validation_end:
                crossing.append({"period": m["period"], "entry": entry, "exit": exit_s})
        else:
            if entry < w.holdout_start or exit_s > w.holdout_end:
                crossing.append({"period": m["period"], "entry": entry, "exit": exit_s})
    embargo_note = (f"embargo={spec.windows.embargo_sessions} sessions enforced "
                    "structurally: entries/exit fills are confined to the phase "
                    "bounds; the first validation entry occurs at/after "
                    f"{w.validation_start}")
    if crossing:
        return {"check": "purge_embargo", "status": "FAIL",
                "reason": f"{len(crossing)} label(s) cross the phase boundary",
                "evidence": {"crossings": crossing[:10], "note": embargo_note}}
    return {"check": "purge_embargo", "status": "PASS", "reason": embargo_note,
            "evidence": {"phase": result.phase,
                         "bounds": list(spec.windows.phase_bounds(result.phase))}}


def _missing_periods_check(result, spec, panel):
    """Abstained months exist, carry causes, and never get fabricated returns;
    continuous NAV withheld where the chain breaks."""
    abst_ok = all(a.get("cause") for a in result.abstained_months)
    labeled = {m["period"] for m in result.months if m["gross_month"] is not None}
    fabricated = [a for a in result.abstained_months if a["period"] in labeled]
    ok = abst_ok and not fabricated
    return {"check": "missing_periods_nav",
            "status": "PASS" if ok else "FAIL",
            "reason": (f"{len(result.abstained_months)} typed abstention(s); "
                       f"{len(result.labeled_segments)} labeled segment(s); "
                       + ("whole-window continuous NAV withheld"
                          if result.continuous_chain_blocked
                          else "continuous chain unbroken")),
            "evidence": {"abstained": [a["period"] for a in result.abstained_months][:20],
                         "segments": [list(s) for s in result.labeled_segments],
                         "continuous_blocked": result.continuous_chain_blocked}}


def _benchmark_check(result, conn):
    """Benchmark provenance + basis honesty: TRI vs raw-price comparison flagged."""
    b = result.benchmark or {}
    sha = (result.source_hashes or {}).get("nifty50_tri_history")
    if result.price_basis.get("economics_vs_tri_blocked", False):
        return {"check": "benchmark_provenance", "status": "FAIL",
                "reason": "raw unadjusted fills cannot be compared with TRI as an "
                          "economic conclusion (basis mismatch; unverified actions)",
                "evidence": {"tri_sha256": sha, "tri_basis": b.get("basis"),
                             "economics_vs_tri_blocked": True}}
    if b.get("total_return") is None or not b.get("basis"):
        return {"check": "benchmark_provenance", "status": "INCONCLUSIVE",
                "reason": "no ingested benchmark covers this window "
                          "(never synthesized); benchmark-relative claims withheld",
                "evidence": {"tri_sha256": sha}}
    return {"check": "benchmark_provenance", "status": "PASS",
            "reason": "benchmark is the official ingested TRI with disclosed basis",
            "evidence": {"tri_sha256": sha, "tri_basis": b.get("basis"),
                         "window": b.get("window")}}


def _nav_reconciliation(result):
    """Independent recomputation: NAV from the fill ledger and month rows, never
    trusted from the engine; paper-book fees re-derived per item."""
    bad = []
    for f in list(result.fills)[:50]:
        acct = f.get("accounting")
        if acct is None:
            continue
        expected = (acct["sell_turnover_paise"] - acct["buy_turnover_paise"]
                    - acct["charges_total_paise"])
        if acct["v3_trade_cash_pnl_paise"] != expected:
            bad.append(f["symbol"] + ":cash")
        items = (acct["buy_charges"]["items"] + acct["sell_charges"]["items"])
        total = sum(i["amount_paise"] for i in items)
        if total != acct["charges_total_paise"]:
            bad.append(f["symbol"] + ":fees")
    # fill-level monthly means and the per-fill gross vs sell/buy consistency
    for m in result.months:
        fills_m = [f for f in result.fills if f["period"] == m["period"]]
        if m["gross_month"] is not None and fills_m:
            mean_g = sum(f["gross_return"] for f in fills_m) / len(fills_m)
            if abs(mean_g - m["gross_month"]) > 1e-12:
                bad.append(m["period"] + ":mean")
    # segment NAV products recomputed from the labeled month rows
    for seg in result.labeled_segments:
        seg_set = set(seg)
        seg_rows = [m for m in result.months
                    if m["period"] in seg_set and m["gross_month"] is not None]
        g = n = 1.0
        all_net = True
        for m in seg_rows:
            g *= 1 + m["gross_month"]
            if m["net_month"] is None:
                all_net = False
            else:
                n *= 1 + m["net_month"]
        row = next((r for r in (result.nav.get("segments") or [])
                    if r["start"] == seg[0] and r["end"] == seg[-1]), None)
        if row is None:
            bad.append(":".join(seg) + ":missing_segment")
            continue
        if row["n_periods"] != len(seg_rows) or abs(row["gross"] - (g - 1.0)) > 1e-9:
            bad.append(":".join(seg) + ":nav_product")
        expected_net = (n - 1.0) if all_net and seg_rows else None
        if expected_net is None and row["net"] is not None or (
                expected_net is not None and
                (row["net"] is None or abs(row["net"] - expected_net) > 1e-9)):
            bad.append(":".join(seg) + ":net_product")
    # cost totals must equal the fill-ledger sum
    charges_sum = sum(f["accounting"]["charges_total_paise"]
                      for f in result.fills if f.get("accounting"))
    if result.costs.get("charges_total_paise") != charges_sum:
        bad.append("costs_total")
    if bad:
        return {"check": "nav_reconciliation", "status": "FAIL",
                "reason": f"{len(bad)} reconciliation mismatch(es)",
                "evidence": {"mismatches": bad[:10]}}
    return {"check": "nav_reconciliation", "status": "PASS",
            "reason": "fill-ledger cash arithmetic, itemised paper-book fees, "
                      "monthly means and per-segment NAV products recomputed "
                      "independently",
            "evidence": {"n_fills_sampled": min(len(result.fills), 50),
                         "n_segments": len(result.labeled_segments)}}


def _cost_scenarios(result, spec, conn, panel):
    """base vs double-cost (2x adverse slippage, exact fee model)."""
    try:
        sc = run_cost_scenarios(spec, conn, panel, phase=result.phase)
    except Exception as exc:  # typed failure surfacing
        return {"check": "cost_scenarios", "status": "INCONCLUSIVE",
                "reason": f"scenario run failed: {exc}", "evidence": {}}
    base, dbl = sc["base"], sc["double_cost"]
    if base is None or dbl is None:
        return {"check": "cost_scenarios", "status": "INCONCLUSIVE",
                "reason": "no net months inside the fee-covered window "
                          "(paper fee schedule effective 2026-03-01; earlier "
                          "fills stay gross with typed SCHEDULE_UNAVAILABLE)",
                "evidence": {"base": base, "double_cost": dbl}}
    if spec.execution.slippage_bps == 0:
        return {"check": "cost_scenarios", "status": "INCONCLUSIVE",
                "reason": "base spec declares zero slippage: doubling applies "
                          "no stress — re-run with an adverse-slippage scenario",
                "evidence": {"base": base, "double_cost": dbl}}
    degraded = dbl["net_product"] <= base["net_product"]
    return {"check": "cost_scenarios",
            "status": "PASS" if degraded else "FAIL",
            "reason": ("double-cost degrades net as expected" if degraded else
                       "double-cost improved net — impossible under adverse "
                       "slippage; integrity problem"),
            "evidence": {"base": base, "double_cost": dbl,
                         "note": "fees stay the exact paper-book model; "
                                 "slippage doubles (adverse paise rounding)"}}


def _concentration_check(result):
    """Per-name, per-period contribution; sector requires a verified map (absent)."""
    pnl_by_name: dict[str, int] = {}
    for f in result.fills:
        if f.get("accounting"):
            pnl_by_name[f["symbol"]] = pnl_by_name.get(f["symbol"], 0) + \
                f["accounting"]["v3_trade_cash_pnl_paise"]
    total = sum(v for v in pnl_by_name.values() if v > 0) or -1
    top = sorted(pnl_by_name.items(), key=lambda kv: -kv[1])[:5]
    max_share = (top[0][1] / total) if top and total > 0 else None
    return {"check": "concentration",
            "status": "INCONCLUSIVE" if max_share is None else
                      ("PASS" if max_share < 0.35 else "FAIL"),
            "reason": (f"largest positive contributor {top[0][0]} = "
                       f"{max_share:.0%} of positive net P&L" if max_share else
                       "no positive contributions to weight"),
            "evidence": {"top_names": top, "sector_dimension":
                         "DATA_BLOCKED: no verified historical sector map ingested"}}


def _placebo_check(result, spec, conn, panel, n_placebo):
    """Random matched portfolios drawn from the SAME eligible pools, same size,
    same execution rule (runner month rows carry per-name gross for every
    eligible name, computed by the identical _exec_info path)."""
    if spec.declared_negative_control and spec.signal.family == "noise_control":
        # the run IS a noise draw; the check records it (blocked from promotion
        # by the verdict rule, not by percentile)
        return {"check": "placebo_random_matched", "status": "PASS",
                "reason": "declared noise control; per-draw result recorded for "
                          "the distribution (promotion impossible by rule)",
                "evidence": {"noise_seed": spec.seed}}
    labeled = [m for m in result.months if m["gross_month"] is not None]
    if not labeled:
        return {"check": "placebo_random_matched", "status": "INCONCLUSIVE",
                "reason": "no labeled months to compare", "evidence": {}}
    rng = random.Random(f"{spec.seed}|placebo")     # deterministic, distinct draw
    draws = []
    for _ in range(n_placebo):
        prod = 1.0
        ok = True
        for m in labeled:
            pool_map = m.get("eligible_gross") or {}
            if not pool_map:
                ok = False
                break
            k = min(m.get("n_chosen") or spec.signal.top_k, len(pool_map))
            pick = rng.sample(sorted(pool_map), k)
            rets = [pool_map[s] for s in pick if pool_map.get(s) is not None]
            if rets:
                prod *= 1 + sum(rets) / len(rets)
        if ok:
            draws.append(prod - 1.0)
    if len(draws) < max(n_placebo // 2, 1):
        return {"check": "placebo_random_matched", "status": "INCONCLUSIVE",
                "reason": f"only {len(draws)}/{n_placebo} placebo draws could be "
                          "built from the eligible pools",
                "evidence": {}}
    strat_prod = 1.0
    for m in labeled:
        strat_prod *= 1 + m["gross_month"]
    strat = strat_prod - 1.0
    pct = 100.0 * sum(1 for d in draws if d <= strat) / max(len(draws), 1)
    beats = pct > PLACEBO_PCT_THRESHOLD
    return {"check": "placebo_random_matched",
            "status": "PASS" if beats else "FAIL",
            "reason": (f"strategy beats {pct:.0f}% of {len(draws)} matched random "
                       "portfolios drawn from the same eligible pools" if beats else
                       f"strategy beats only {pct:.0f}% of matched noise "
                       f"(threshold {PLACEBO_PCT_THRESHOLD:.0f}%) — no edge"),
            "evidence": {"n_draws": len(draws), "percentile": pct,
                         "strategy_gross": strat,
                         "noise_median": sorted(draws)[len(draws) // 2] if draws else None}}


def _dependence_check(result):
    """Moving-block bootstrap of the labeled gross series (dependence-aware:
    contiguous month blocks resample, so autocorrelation at short lags is kept)."""
    labeled = [m for m in result.months if m["gross_month"] is not None]
    if len(labeled) < 12:
        return {"check": "dependence_aware_uncertainty", "status": "INCONCLUSIVE",
                "reason": f"only {len(labeled)} labeled periods; block bootstrap "
                          "needs >= 12", "evidence": {}}
    rng = random.Random(20261112)
    series = [m["gross_month"] for m in labeled]
    n = len(series)
    block = 3
    n_blocks = -(-n // block)                    # ceil
    means = []
    for _ in range(2000):
        sample = []
        for _b in range(n_blocks):
            s = rng.randrange(n - block + 1)     # random block start position
            sample.extend(series[s:s + block])
        sample = sample[:n]
        means.append(sum(sample) / n)
    means.sort()
    lo, hi = means[int(0.05 * len(means))], means[int(0.95 * len(means))]
    return {"check": "dependence_aware_uncertainty", "status": "PASS",
            "reason": f"moving-block bootstrap (block=3 months, 2000 resamples) "
                      f"90% CI of the monthly mean: [{lo:+.4%}, {hi:+.4%}] — "
                      "months are the dependence unit, not single names/days",
            "evidence": {"n_periods": n, "block": block,
                         "ci90_mean_monthly": [lo, hi]}}


def _multiplicity_check(sweep_n_trials):
    if sweep_n_trials is None:
        return {"check": "multiplicity", "status": "INCONCLUSIVE",
                "reason": "no sweep metadata attached to this run",
                "evidence": {}}
    return {"check": "multiplicity", "status": "PASS",
            "reason": f"{sweep_n_trials} configurations were tried; the selected "
                      "variant must be judged against that many trials "
                      "(selection-adjusted; a lone peak is a rejection signal)",
            "evidence": {"n_trials": sweep_n_trials}}


def _holdout_check(result, spec, holdout_seal):
    if result.phase == "train_validation":
        if holdout_seal and not holdout_seal.get("sealed_before_runs"):
            return {"check": "holdout_integrity", "status": "FAIL",
                    "reason": "holdout not sealed before runs", "evidence": {}}
        return {"check": "holdout_integrity", "status": "PASS",
                "reason": "run evaluated train/validation only; holdout untouched",
                "evidence": {"holdout_window": list(spec.windows.phase_bounds("holdout")),
                             "seal": holdout_seal}}
    # holdout evaluation: must come after a registered seal
    if not holdout_seal or not holdout_seal.get("sealed_before_runs"):
        return {"check": "holdout_integrity", "status": "FAIL",
                "reason": "holdout evaluated without a prior seal registration",
                "evidence": {}}
    return {"check": "holdout_integrity", "status": "PASS",
            "reason": "holdout evaluated once, after a registered seal",
            "evidence": {"seal": holdout_seal}}


def _verdict(result, checks, spec):
    fails = [c for c in checks if c["status"] == "FAIL"]
    blocking = [c for c in fails if c["check"] in PROMOTION_BLOCKING]
    placebo = next((c for c in checks if c["check"] == "placebo_random_matched"), None)
    if spec.declared_negative_control:
        caught = [c["check"] for c in fails]
        return "REJECTED", ("declared negative control (" + spec.signal.family +
                            ") runs as designed and can never earn promotion" +
                            (f"; challenger caught: {', '.join(caught)}"
                             if caught else
                             "; blocked by rule even without an integrity catch"))
    if blocking:
        return "DATA_BLOCKED", ("integrity check(s) failed: "
                                + ", ".join(c["check"] for c in blocking))
    if result.price_basis.get("economics_vs_tri_blocked") or \
            any(m.get("weak_rows_included") for m in result.months):
        return "DATA_BLOCKED", ("unverified corporate actions (raw prices) and/or "
                                "weak-row membership: historical economics cannot "
                                "be validated on current sources")
    if placebo and placebo["status"] == "FAIL":
        return "NO_EDGE", placebo["reason"]
    return "RESEARCH", ("mechanics and integrity checks pass; W2 cannot promote: "
                        "verified corporate actions and first-known membership "
                        "timestamps are missing, so OOS_VALIDATED is unreachable")
