"""W1 final: first fully reproduced simple strategy on the real V3.1 panel.

PREREGISTERED SPEC (frozen before the run; deviating requires a new spec):

- Universe: NIFTY 50 as-of membership at each decision (`members_at`, default
  mode — snapshot_floor spells included and disclosed; PARTIAL status carried).
- Decisions: 00:15 IST on the month's first *observed* session (sees the prior
  session's close; same-session data is never available — availability rule
  session + 1 local day + 15 min).
- Entry: next executable OPEN after the decision — for every eligible name the
  month's first observed session (`labels.ENTRY_POLICY`). Eligible = member
  has an EQ bar on that session; others abstain (disclosed per month).
- Exit: the **next rebalance's execution price** — the OPEN of the following
  month's first observed session (`exit_ref="OPEN"`). The monthly chain then
  rolls execution price to execution price with no skipped boundary move
  (an exit at the pre-boundary close followed by a re-entry at the next open
  would silently drop ~13 overnight moves per year — measured at +40.56%
  vs +82.76% close-to-close in the first build of this artifact; the
  execution-to-execution convention is the economically correct one).
  Conservative labelled extension (<=5 sessions) when a name does not trade
  on the target session; NO_FILL abstains otherwise.
- Accounting: integer paise via `economics.trade_cash_pnl`, Rs 1,00,000
  notional per name. Charges are a full-notional round trip per name per
  month at the actual execution prices — a conservative UPPER BOUND on
  equal-weight rebalance costs.
- Corporate actions: bars are RAW unadjusted official prices and no verified
  local action history exists (`app/data/corporate_actions.py`: "No verified
  source history is available in this repo"). Adjustment therefore abstains
  (UNKNOWN, never imputed). Splits/bonuses/demergers inside a holding window
  register as price discontinuities; the artifact scans and quantifies them
  (close/prev_close < 0.65 or > 1.54 — impossible as ordinary moves for
  index names) so the TRI comparison can be judged with eyes open. Suspected
  windows are REPORTED, never silently excluded (dropping them would bias
  the sample upward, a survivorship-flavoured distortion).
- Fee coverage: schedule `nse-cm-delivery-2026-03-01` is effective
  2026-03-01 onward. Months entering earlier are GROSS-ONLY with
  `charges_status=SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE`; net metrics
  None. A month is never priced with a later schedule.
- Benchmark: official NIFTY50 TRI (`benchmark_total_return`, T+1 joins).
  Strategy-minus-TRI is reported as benchmark-relative excess — never cash.
- Gaps: months with no observed session (the 2024 H1 archive hole) are
  recorded as abstentions with cause MISSING_SPAN — never interpolated.
- Labels: RETROSPECTIVE reconstruction from official archived bars; as-of
  membership means SURVIVOR_BIASED does not apply (and must not be claimed).

Outputs `reports/alpha_v3_1/wave1_first_strategy_reproduction.{json,md}`.
No network, no V2 mutation, paper-only.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend-extension"))

from quantplus_intelligence.research_v3 import economics  # noqa: E402
from quantplus_intelligence.research_v3 import labels as L  # noqa: E402
from quantplus_intelligence.research_v3 import warehouse as W  # noqa: E402

REPORTS = REPO / "reports" / "alpha_v3_1"
UNIVERSE = "nifty50"
NOTIONAL_PAISE = L.DEFAULT_NOTIONAL_PAISE  # Rs 1,00,000 per name


def _has_bar_on(conn, symbol: str, session: str) -> bool:
    """Alias-aware check: the instrument traded this session (EQ)."""
    aliases = W.alias_symbols_at(conn, symbol, session)
    marks = ",".join("?" * len(aliases))
    row = conn.execute(
        f"SELECT 1 FROM daily_bars WHERE symbol IN ({marks}) AND session=? "
        "AND series='EQ' LIMIT 1", (*aliases, session)).fetchone()
    return row is not None


ACTION_GAP_LO = 0.65   # close/prev_close below this = split/bonus/demerger shape
ACTION_GAP_HI = 1.54   # above this = consolidation shape (1/0.65)


def _action_gaps_in_window(conn, symbol: str, lab: dict) -> list[dict]:
    """Overnight price discontinuities inside the label's holding window.

    Raw bhavcopy ``prev_close`` is the raw prior close (proved by the detected
    bonus/split gaps), so ``close/prev_close`` outside [0.65, 1.54] is an
    unadjusted corporate action or a demerger — never an ordinary move for an
    index name. Returned for DISCLOSURE only: windows are never dropped
    (selective dropping would bias the sample upward). No factor is imputed.
    """
    aliases = W.alias_symbols_at(conn, symbol, lab["exit"]["session"])
    marks = ",".join("?" * len(aliases))
    rows = conn.execute(
        f"SELECT session, open_paise, close_paise, prev_close_paise FROM daily_bars "
        f"WHERE symbol IN ({marks}) AND series='EQ' AND session>=? AND session<=? "
        "ORDER BY session", (*aliases, lab["entry"]["session"],
                             lab["exit"]["session"])).fetchall()
    out = []
    for i, (s, o, c, pc) in enumerate(rows):
        for kind, ratio in (("close/prev_close", c / pc if pc else None),
                            ("open/prev_close", o / pc if pc else None)):
            if ratio is not None and (ratio < ACTION_GAP_LO or ratio > ACTION_GAP_HI):
                out.append({"session": s, "kind": kind, "ratio": round(ratio, 4)})
    return out


def _month_first_sessions(observed: list[str]) -> dict[str, str]:
    """YYYY-MM -> first observed session of that month."""
    out: dict[str, str] = {}
    for s in observed:
        out.setdefault(s[:7], s)
    return out


def run_universe(conn, observed: list[str], firsts: dict[str, str],
                 pos: dict[str, int], months: list[str], *, strict: bool,
                 verbose: bool = False) -> dict:
    """One full EW-NIFTY50 monthly-rebalance run over the observed months."""
    month_rows: list[dict] = []
    cum_gross = 1.0
    net_chain = 1.0
    net_months = 0
    abstain: list[dict] = []

    for i, m in enumerate(months):
        F = firsts.get(m)
        if F is None:
            abstain.append({"month": m, "cause": "MISSING_SPAN",
                            "note": "no observed session in this month "
                                    "(2024 H1 archive hole); nothing decided, "
                                    "nothing fabricated"})
            continue
        nxt = months[i + 1] if i + 1 < len(months) else None
        if nxt is None or nxt not in firsts:
            abstain.append({"month": m, "cause": "NO_NEXT_REBALANCE",
                            "note": "data ends before the next rebalance; "
                                    "position would be open at data end — "
                                    "not labelled, never closed synthetically"})
            continue
        F_next = firsts[nxt]
        horizon = pos[F_next] - pos[F]  # entry at F open, exit at F_next OPEN
        decision_ts = f"{F}T00:15:00+05:30"

        mem = W.members_at(conn, UNIVERSE, decision_ts, strict=strict)
        if mem.status == "UNKNOWN":
            abstain.append({"month": m, "cause": "MEMBERSHIP_UNKNOWN",
                            "status": mem.status,
                            "note": "no membership coverage at this date; "
                                    "universe not assumed"})
            continue

        eligible = [s for s in mem.rows if _has_bar_on(conn, s, F)]
        ok, no_fill, entry_mismatch = [], 0, 0
        for sym in eligible:
            lab = L.executable_label(conn, sym, decision_ts, horizon,
                                     notional_paise=NOTIONAL_PAISE,
                                     observed_sessions=observed,
                                     exit_ref="OPEN")
            if lab["status"] != "OK" or lab["entry"]["session"] != F:
                entry_mismatch += lab["entry"]["session"] != F if lab["status"] == "OK" else 0
                no_fill += 1
                continue
            lab["action_discontinuities"] = _action_gaps_in_window(conn, sym, lab)
            ok.append(lab)

        row = {"month": m, "decision_ts": decision_ts,
               "entry_session": F, "exit_session_target": None,
               "membership_status": mem.status,
               "n_members": len(mem.rows), "n_eligible": len(eligible),
               "n_ok": len(ok), "n_no_fill": no_fill,
               "entry_session_mismatch": entry_mismatch,
               "weak_rows_included": mem.meta.get("weak_rows_included"),
               "charges_status": None, "gross_month": None, "net_month": None,
               "n_action_discontinuity_windows": 0,
               "action_discontinuity_examples": []}
        if ok:
            row["exit_session_target"] = ok[0]["exit"]["session"]
            row["gross_month"] = sum(l["v3_gross_absolute"] for l in ok) / len(ok)
            statuses = {l["charges_status"] for l in ok}
            row["charges_status"] = "+".join(sorted(statuses))
            if statuses == {"OK"}:
                row["net_month"] = sum(l["accounting"]["v3_net_absolute"] for l in ok) / len(ok)
                net_chain *= 1.0 + row["net_month"]
                net_months += 1
            cum_gross *= 1.0 + row["gross_month"]
            gaps = [(l["symbol"], l["action_discontinuities"])
                    for l in ok if l["action_discontinuities"]]
            row["n_action_discontinuity_windows"] = len(gaps)
            row["action_discontinuity_examples"] = [
                {"symbol": s, "events": g[:3]} for s, g in gaps[:5]]
        else:
            abstain.append({"month": m, "cause": "NO_FILLS",
                            "note": f"{len(eligible)} eligible members produced "
                                    "no executable label"})
        month_rows.append(row)
        if verbose and row["gross_month"] is not None:
            print(f"  {m}: members={row['n_members']} ok={row['n_ok']} "
                  f"gross={row['gross_month']:+.4%} net={row['net_month']}")

    return {"months": month_rows, "abstain": abstain,
            "cumulative_gross": cum_gross, "net_chain_covered": net_chain,
            "net_months": net_months}


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    db = REPO / "backend-extension" / "data" / "research_v3" / "warehouse.sqlite3"
    conn = W.connect(str(db))
    print(f"warehouse: {db}")

    observed = W.sessions(conn)
    pos = {s: i for i, s in enumerate(observed)}
    firsts = _month_first_sessions(observed)
    all_months = sorted({s[:7] for s in observed})
    span_months = [f"{y}-{mm:02d}" for y in range(2015, 2027) for mm in range(1, 13)
                   if f"{y}-{mm:02d}" <= observed[-1][:7]]
    print(f"observed sessions: {len(observed)} ({observed[0]}..{observed[-1]}), "
          f"months spanned: {len(span_months)}")

    # --- default run: disclosed membership (PARTIAL where snapshot rows) ------
    print("running equal-weight NIFTY50 monthly rebalance (disclosed membership)...")
    run = run_universe(conn, observed, firsts, pos, span_months, strict=False)

    # --- strict run: VERIFIED membership only (secondary comparison) ----------
    print("running strict-membership variant...")
    strict_run = run_universe(conn, observed, firsts, pos, span_months,
                              strict=True, verbose=False)

    # --- benchmark reproduction -------------------------------------------------
    labeled = [r for r in run["months"] if r["gross_month"] is not None]
    gap_windows = sum(m["n_action_discontinuity_windows"] for m in run["months"])
    gap_months = [m["month"] for m in run["months"] if m["n_action_discontinuity_windows"]]
    gap_examples = [ex for m in run["months"]
                    for ex in m["action_discontinuity_examples"]]
    s0 = labeled[0]["entry_session"]
    s1 = labeled[-1]["exit_session_target"]
    bench = W.benchmark_total_return(conn, "NIFTY50_TRI", s0, s1)
    years = (date.fromisoformat(s1) - date.fromisoformat(s0)).days / 365.25
    strat_cagr = run["cumulative_gross"] ** (1 / years) - 1
    tri_cagr = 1.0 + bench["total_return"]
    tri_cagr = tri_cagr ** (1 / years) - 1
    excess = run["cumulative_gross"] - (1.0 + bench["total_return"])

    # per-year TRI + strategy
    yearly = []
    for y in sorted({m["month"][:4] for m in labeled}):
        ym = [m for m in labeled if m["month"][:4] == y]
        g = 1.0
        for m in ym:
            g *= 1.0 + m["gross_month"]
        b = W.benchmark_total_return(conn, "NIFTY50_TRI", ym[0]["entry_session"],
                                     ym[-1]["exit_session_target"])
        yearly.append({
            "year": y, "strategy_gross": g - 1.0,
            "nifty50_tri": b["total_return"],
            "excess_benchmark_relative": (g - 1.0) - b["total_return"],
            "n_labeled_months": len(ym),
            "n_abstain_months": len([a for a in run["abstain"] if a["month"][:4] == y]),
            "mean_breadth_ok_over_eligible": (
                sum(m["n_ok"] / m["n_eligible"] for m in ym) / len(ym)) if ym else None,
            "mean_n_ok": sum(m["n_ok"] for m in ym) / len(ym),
        })

    result = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "spec": __doc__.strip().split("PREREGISTERED SPEC")[0][:0] or {
            "strategy": "equal-weight NIFTY50, monthly rebalance, as-of membership",
            "universe": UNIVERSE,
            "decision_rule": "00:15 IST on the month's first observed session",
            "entry": L.ENTRY_POLICY, "exit": L.EXIT_POLICY,
            "notional_paise_per_name": NOTIONAL_PAISE,
            "membership_mode": "default (snapshot_floor disclosed; PARTIAL)",
            "benchmark": "official NIFTY50 TRI via benchmark_total_return (T+1 joins)",
            "fee_policy": "full-notional round-trip per name per month (conservative "
                          "upper bound); gross-only before 2026-03-01",
            "attribution": W.ATTRIBUTION_MEMBERSHIP,
        },
        "labels": {
            "retrospective": "backtest over archived official records — not a forward "
                             "prediction",
            "survivorship": "none — membership is as-of at every decision; "
                            "SURVIVOR_BIASED must not be claimed",
            "benchmark_relative": "strategy-minus-TRI is excess vs benchmark; "
                                  "NEVER display as cash profit",
            "bars_source_class": W.SOURCE_CLASS_BHAVCOPY,
        },
        "panel": {"observed_sessions": len(observed),
                  "first_session": observed[0], "last_session": observed[-1],
                  "membership_attribution": W.ATTRIBUTION_MEMBERSHIP},
        "default_run": {
            "cumulative_gross": run["cumulative_gross"],
            "strategy_cagr_gross": strat_cagr,
            "nifty50_tri_total_return": bench["total_return"],
            "nifty50_tri_cagr": tri_cagr,
            "excess_benchmark_relative": excess,
            "excess_claim": "v3_benchmark_relative semantics — excess vs benchmark, "
                            "never cash profit",
            "net_chain_over_covered_months": run["net_chain_covered"] - 1.0,
            "net_months_covered": run["net_months"],
            "net_note": "net chained ONLY over months whose entry falls on/after "
                        "2026-03-01 (fee truth); earlier months are gross-only "
                        "with charges_status=SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE",
            "action_discontinuities": {
                "suspected_windows": gap_windows,
                "months_affected": gap_months,
                "examples": gap_examples,
                "policy": "windows are REPORTED, never dropped (dropping would "
                          "bias upward); no factor is imputed; adjustment status "
                          "stays UNKNOWN until a verified corporate-actions "
                          "source is ingested",
                "consequence": "the strategy-vs-TRI comparison is NOT economically "
                               "interpretable: TRI assumes action-adjusted holding, "
                               "the strategy holds raw unadjusted prices",
            },
            "n_labeled_months": len(labeled),
            "n_abstain_months": len(run["abstain"]),
            "abstain": run["abstain"],
            "months": run["months"],
        },
        "strict_run": {
            "cumulative_gross": strict_run["cumulative_gross"],
            "n_labeled_months": len([m for m in strict_run["months"]
                                     if m["gross_month"] is not None]),
            "n_abstain_months": len(strict_run["abstain"]),
            "note": "VERIFIED membership only (press_release/merger/amendment); "
                    "months with thin coverage abstain rather than assume",
            "abstain_causes": sorted({a["cause"] for a in strict_run["abstain"]}),
        },
        "yearly": yearly,
        "claim": "fully reproduced from immutable official archives; every month "
                 "carries its breadth and charges status; abstentions are "
                 "recorded, never filled",
    }
    out_json = REPORTS / "wave1_first_strategy_reproduction.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    # --- markdown --------------------------------------------------------------
    lines = [
        "# Wave 1 — first fully reproduced strategy (EW NIFTY50 monthly rebalance)",
        "",
        f"Generated: {result['generated_at']} · Preregistered spec in "
        "`backend-extension/scripts/wave1_first_strategy.py` · Machine data: "
        "`wave1_first_strategy_reproduction.json`",
        "",
        "**Honesty labels**: RETROSPECTIVE (archived official bars) · as-of "
        "membership → not survivor-biased · benchmark-relative excess is NOT "
        "cash profit · net figures exist only where fee truth covers them "
        "(2026-03-01+), gross-only before.",
        "",
        "## Benchmark reproduction (official NIFTY50 TRI)",
        "",
        f"Window {s0} → {s1} ({years:.2f} y): total return "
        f"**{bench['total_return']:+.2%}**, CAGR **{tri_cagr:+.2%}**, basis "
        f"`{bench['basis']}`.",
        "",
        "## Equal-weight NIFTY50 (as-of membership, monthly rebalance)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cumulative gross | **{run['cumulative_gross'] - 1.0:+.2%}** "
        f"(CAGR {strat_cagr:+.2%}) |",
        f"| Excess vs TRI (benchmark-relative) | **{excess:+.2%}** |",
        f"| Labeled months | {len(labeled)} of {len(span_months)} spanned "
        f"({len(run['abstain'])} abstained) |",
        f"| Net (covered months only, 2026-03-01+) | "
        f"{(run['net_chain_covered'] - 1.0) if run['net_months'] else 'not covered yet'}"
        f" over {run['net_months']} months |",
        f"| Mean monthly breadth (OK/eligible) | "
        f"{sum(m['n_ok'] / m['n_eligible'] for m in labeled) / max(len(labeled), 1):.1%} |",
        "",
        "## Per year (gross, disclosed membership)",
        "",
        "| Year | Strategy gross | TRI | Excess (rel.) | Months labeled | Mean n OK |",
        "|---|---|---|---|---|---|",
    ]
    for y in yearly:
        lines.append(f"| {y['year']} | {y['strategy_gross']:+.2%} | "
                     f"{y['nifty50_tri']:+.2%} | {y['excess_benchmark_relative']:+.2%} | "
                     f"{y['n_labeled_months']} | {y['mean_n_ok']:.1f} |")
    lines += [
        "",
        "## Unadjusted corporate actions — quantified, disclosed, never imputed",
        "",
        f"**{gap_windows} name-month holding windows** contain at least one "
        f"overnight price discontinuity "
        f"(close/prev_close < {0.65} or > {1.54} — split/bonus/demerger or "
        "consolidation shape, impossible as an ordinary move for index names), "
        f"across {len(gap_months)} months. These windows are measured with RAW "
        "prices: no verified corporate-actions source exists locally "
        "(`app/data/corporate_actions.py`: \"No verified source history is "
        "available in this repo\"), so the adjustment factor abstains (UNKNOWN) "
        "and no factor is inferred from the gap.",
        "",
        "Consequence: **the strategy-vs-TRI comparison above is NOT "
        "economically interpretable** — TRI assumes action-adjusted, "
        "dividend-reinvested holding; the strategy holds raw prices. The "
        "comparison is retained as the honest raw measurement plus this "
        "quantified caveat; suspected windows are deliberately NOT excluded "
        "(dropping e.g. a genuine crash would bias the sample upward).",
        "",
        "Examples of detected discontinuities:",
        "",
    ]
    for ex in gap_examples[:10]:
        ev = "; ".join(f"{e['session']} {e['kind']}×{e['ratio']}" for e in ex["events"])
        lines.append(f"- {ex['symbol']}: {ev}")
    lines += [
        "",
        "## Abstentions (recorded, never filled)",
        "",
    ]
    by_cause: dict[str, list[str]] = {}
    for a in run["abstain"]:
        by_cause.setdefault(a["cause"], []).append(a["month"])
    for cause, ms in sorted(by_cause.items()):
        shown = ", ".join(ms[:8]) + (" …" if len(ms) > 8 else "")
        lines.append(f"- **{cause}** ({len(ms)} months): {shown}")
    lines += [
        "",
        "## Strict-membership variant (secondary)",
        "",
        f"Cumulative gross {strict_run['cumulative_gross'] - 1.0:+.2%} over "
        f"{len([m for m in strict_run['months'] if m['gross_month'] is not None])} "
        f"labeled months ({len(strict_run['abstain'])} abstained; causes: "
        f"{', '.join(sorted({a['cause'] for a in strict_run['abstain']})) or 'none'}).",
        "",
        "## Notes",
        "",
        "- Fees: full-notional round trip per name per month via `economics.py` "
        "(integer paise) — a conservative UPPER BOUND on equal-weight turnover "
        "costs; real drift-rebalanced turnover would charge less.",
        "- The 2024 H1 archive hole produces abstention months, not gaps in the "
        "chain; the product is over labeled months only and the skipped months "
        "are listed above.",
        "- Membership attribution (CC BY 4.0) is carried in the JSON and on every "
        "warehouse row: Jha, A. (2026), github.com/aditya-jha/"
        "nse-historical-membership.",
        "- This reproduction may be *honestly rejected* by later waves; it is the "
        "W1 acceptance exercise for the data+fee stack, not a production signal.",
    ]
    out_md = REPORTS / "wave1_first_strategy_reproduction.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_json}\nwrote {out_md}")
    print(f"cumulative gross {run['cumulative_gross'] - 1.0:+.2%} vs TRI "
          f"{bench['total_return']:+.2%}; labeled months {len(labeled)}/{len(span_months)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
