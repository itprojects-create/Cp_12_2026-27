"""Forward event-blackout experiment harness (P3, §§39–46).

Control A (champion v4 core, no blackout) vs B1/B2/B3 (champion + frozen
BLACKOUT_FAMILY_V1 rule via per-bar PIT-eligible entry gating). Same capital
(unit equity), universe, caps, costs, schedule — only blackout behavior differs.
No LLM overlay anywhere.

PIT discipline: at decision bar t only announcements with
decision_eligibility_ts (= max(publication, ingestion) + buffer) <= bar date
may gate entries. Forward-only: bars before experiment forward_start are never
scored (infancy when the eligible sample is below manifest minimums).

Metrics: event-level §42 (factual observables + blocked flags; portfolio effect
at window level as control-vs-candidate gap — joint attribution disclosed),
risk §43, opportunity cost §44 (factual counts/returns, no invented notionals),
net utility §45 (components only, no hidden weights).

Usage:
  python scripts/run_event_blackout_forward.py --manifest data/event_blackout_v1_manifest.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.trend_core_v4 import run_core_v4  # noqa: E402
from app.eval import stats as STATS  # noqa: E402
from app.events import blackout as BO  # noqa: E402

MIN_ELIGIBLE_EVENTS = 30
MIN_COMPANIES = 10
MIN_EVENT_DAYS = 20
DEFAULT_BUFFER_S = 900


def eligibility_ts(pub_iso: str, ing_iso: str, buffer_s: int = DEFAULT_BUFFER_S) -> str:
    """decision_eligibility = max(publication, ingestion) + buffer. Uncertain ->
    later timestamp (callers pass max-known; never assume instant usability)."""
    from datetime import timedelta
    p = datetime.fromisoformat(pub_iso)
    i = datetime.fromisoformat(ing_iso)
    if p.tzinfo is None:
        p = p.replace(tzinfo=timezone.utc)
    if i.tzinfo is None:
        i = i.replace(tzinfo=timezone.utc)
    return (max(p, i) + timedelta(seconds=buffer_s)).isoformat()


def rows_from_store(start_iso: str, end_iso: str,
                    taxonomy_version: str = "EVENT_TAXONOMY_V1",
                    buffer_s: int = DEFAULT_BUFFER_S) -> list[dict]:
    """Join store raws + latest pinned-taxonomy classifications into harness
    rows. effective_ts = publication_ts until meeting-date extraction lands
    (classifier v2) — documented approximation; windows apply around publication."""
    from app.events import store as ST
    rows = []
    for r in ST.announcements_in_range(start_iso, end_iso, taxonomy_version):
        cls = r["classification"] or {}
        rows.append({
            "record_id": r["record_id"], "symbol": r["symbol"],
            "event_type": cls.get("event_type", "OTHER"),
            "severity": float(cls.get("severity", 0.2)),
            "blackout_candidate": bool(cls.get("blackout_candidate", False)),
            "effective_ts": r["publication_ts"],
            "eligibility_ts": eligibility_ts(r["publication_ts"], r["ingestion_ts"],
                                             buffer_s),
            "taxonomy_version": r["taxonomy_version"],
            "classifier_version": r["classifier_version"],
        })
    return rows


def make_gate(rule, announcements: list[dict], buffer_s: int = DEFAULT_BUFFER_S,
              log: list | None = None):
    """entry_gate_fn closure over PIT-eligible announcements. Logs every veto."""
    def gate(name: str, bar: int, date: str | None) -> bool:
        if date is None:
            return True
        cands = [a for a in announcements
                 if a["symbol"] == name and a["eligibility_ts"][:10] <= date[:10]]
        active, _ = BO.rule_active(rule, name,
                                   datetime.fromisoformat(date[:10] + "T00:00:00+00:00"),
                                   [_dict_to_ann(a) for a in cands])
        if active:
            if log is not None:
                log.append({"date": date[:10], "symbol": name, "rule": rule.rule_id})
            return False
        return True
    return gate


def _dict_to_ann(a: dict):
    from app.events.schemas import Announcement
    return Announcement(source="NSE", symbol=a["symbol"], event_type=a["event_type"],
                        severity=a["severity"],
                        source_timestamp=a["effective_ts"],
                        effective_timestamp=a["effective_ts"],
                        blackout_candidate=a["blackout_candidate"])


def _daily(eq: list[float]) -> list[float]:
    return [eq[i] / eq[i - 1] - 1 if eq[i - 1] else 0.0 for i in range(1, len(eq))]


def run_experiment(panel: dict, announcements: list[dict],
                   rules=None, manifest: dict | None = None) -> dict:
    """panel: {index:[..], names:{sym:[..]}, dates:[..]}. Returns the full
    evaluation payload (event rows, risk, opportunity, utility, verdict)."""
    from app.eval import concentration as CONC
    idx, names, dates = panel["index"], panel["names"], panel["dates"]
    rules = list(rules or BO.BLACKOUT_FAMILY_V1)
    # decision bars need 5 forward bars for subsequent-return observables
    horizon = len(idx) - 5
    control = run_core_v4(idx, names)
    ctrl_daily = _daily(control.eq_curve)

    eligible = [a for a in announcements if a.get("blackout_candidate")]
    companies = {a["symbol"] for a in eligible}
    event_days = {a["effective_ts"][:10] for a in eligible}
    sample = {"n_events": len(eligible), "n_companies": len(companies),
              "n_event_days": len(event_days)}

    arms, event_rows = {}, []
    for rule in rules:
        if rule.rule_id == "B0":
            rep = control
            blocked: list = []
        else:
            log: list = []
            gate = make_gate(rule, announcements, log=log)
            rep = run_core_v4(idx, names, dates=dates, entry_gate_fn=gate)
            blocked = log
        cand_daily = _daily(rep.eq_curve)
        arms[rule.rule_id] = {
            "total_return": round(rep.total_return, 6),
            "cagr": round(rep.cagr, 6),
            "max_drawdown": round(rep.max_drawdown, 6),
            "sharpe": round(rep.sharpe, 4),
            "cost": round(rep.total_cost, 6),
            "switches": rep.n_switches,
            "cvar95": round(STATS.cvar(cand_daily), 6),
            "cvar99": round(STATS.cvar(cand_daily, 0.01), 6),
            "blocked_entries": len(blocked),
        }
        if rule.rule_id != "B0":
            event_rows.extend([{**b, "arm": rule.rule_id} for b in blocked])

    # per-blocked-entry subsequent observables (factual, return-space, no notional)
    for row in event_rows:
        try:
            t = dates.index(row["date"])
            cs = names[row["symbol"]]
            rets = {}
            for h in (1, 2, 5):
                if t + h < len(cs) and cs[t] > 0:
                    rets[f"ret_{h}d"] = round(cs[t + h] / cs[t] - 1, 6)
            row.update(rets)
            row["profitable_block"] = rets.get("ret_5d", 0) > 0
        except (ValueError, KeyError, IndexError):
            row["profitable_block"] = None

    missed = sum(1 for r in event_rows if r.get("profitable_block") is True)
    opp = {"blocked_trade_count": len(event_rows),
           "missed_profitable_entries": missed,
           "missed_upside_ret_space": round(sum(r.get("ret_5d", 0) for r in event_rows
                                                if r.get("profitable_block")), 6),
           "capital_idle_days": len({(r["date"], r["symbol"]) for r in event_rows})}
    c0, c1 = arms["B0"], arms.get("B3", arms["B0"])
    utility = {"tail_loss_reduction": None,  # needs mature event sample; see verdict
               "opportunity_cost": round(c0["total_return"] - c1["total_return"], 6),
               "added_cost": round(c1["cost"] - c0["cost"], 6),
               "note": "components only — no combined score, no hidden weights (§45)"}

    ready = (sample["n_events"] >= MIN_ELIGIBLE_EVENTS
             and sample["n_companies"] >= MIN_COMPANIES
             and sample["n_event_days"] >= MIN_EVENT_DAYS)
    verdict = "READY_FOR_GATE" if ready else "EVENT_FORWARD_INFANCY"
    per_event_pnl = [{"event_id": f"{r['symbol']}@{r['date']}", "pnl": r.get("ret_5d", 0),
                      "event_type": next((a["event_type"] for a in eligible
                                          if a["symbol"] == r["symbol"]), "UNKNOWN")}
                     for r in event_rows if r.get("ret_5d") is not None]
    return {"arms": arms, "sample": sample,
            "minimums": {"events": MIN_ELIGIBLE_EVENTS, "companies": MIN_COMPANIES,
                         "event_days": MIN_EVENT_DAYS},
            "event_rows": event_rows, "per_event_pnl": per_event_pnl,
            "concentration": CONC.analyze(
                [{"id": e["event_id"], "pnl": e["pnl"], "sector": e["event_type"]}
                 for e in per_event_pnl]) if per_event_pnl else {"missing": "no events"},
            "opportunity": opp, "utility": utility,
            "control_daily": ctrl_daily[-5:],
            "verdict": verdict,
            "manifest": (manifest or {}).get("experiment_id", "adhoc")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/event_blackout_v1_manifest.json")
    a = ap.parse_args()
    manifest = json.load(open(a.manifest, encoding="utf-8"))
    fwd_start = manifest["forward_start"]
    now = datetime.now(timezone.utc)
    rows = rows_from_store(fwd_start, now.isoformat(),
                           manifest.get("taxonomy_version", "EVENT_TAXONOMY_V1"))
    out = {"experiment": manifest["experiment_id"], "as_of": now.isoformat(),
           "forward_start": fwd_start, "n_announcements": len(rows),
           "panel": "no forward price panel settled yet — infancy",
           "verdict": ("EVENT_FORWARD_INFANCY" if len(
               [r for r in rows if r["blackout_candidate"]]) < MIN_ELIGIBLE_EVENTS
                       else "PANEL_PENDING"),
           "manifest": manifest["experiment_id"]}
    path = os.path.join("data", f"event_blackout_forward_{now.date().isoformat()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("artifact:", path)
    # §74: the experiment lives in research memory (status follows the verdict;
    # §74: the experiment lives in research memory (status follows the verdict;
    # infancy rows accumulate as weekly observations under one hypothesis fp).
    from app.research_memory import store as ST
    ST.init_tables()
    exp_id = ST.record_experiment(
        "hyp-event-blackout-v1",
        {"experiment": manifest["experiment_id"], "manifest": a.manifest,
         "artifact": path, "verdict": out["verdict"],
         "evidence_class": manifest.get("evidence_class", "RISK_CONTROL")},
        status="EXPERIMENTING" if out["verdict"] == "EVENT_FORWARD_INFANCY"
        else "FORWARD_VALIDATING")
    print("memory experiment:", exp_id)


if __name__ == "__main__":
    main()
