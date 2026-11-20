"""Failure-first event report: WHY THIS MAY BE FAKE before benefits (§67).

Consumes a forward-blackout evaluation payload (sample + economics +
coverage) and orders the report per §96: integrity, coverage, classifier
health, PIT, sample, control, candidate, tail effect, opportunity cost,
concentration, failure analysis, verdict, missing evidence.
"""
from __future__ import annotations

from app.eval import concentration as CONC


def failure_first(sample: dict, economics: dict | None = None,
                  coverage: dict | None = None,
                  known_weaknesses: list[str] | None = None) -> dict:
    """sample: {n_events, n_companies, n_event_days, by_type, by_company,
    by_month, top_event_share?, loo_by_type?, verdict_hint?}.
    economics: {tail_loss_reduction, opportunity_cost, added_cost,
    candidate_cvar, control_cvar, candidate_maxdd, control_maxdd, ...} or None.
    coverage: {expected_days, uptime_days, fetch_failures, abstentions, ...}."""
    sample = sample or {}
    fake: list[str] = list(known_weaknesses or [])
    n = int(sample.get("n_events", 0))
    if n < 30:
        fake.append(f"too few events (n={n} < 30 minimum) — any effect is noise")
    if sample.get("taxonomy_error_rate") is None:
        fake.append("taxonomy error rate unmeasured — category labels uncertified")
    if (coverage or {}).get("fetch_failures", 0):
        fake.append(f"{coverage['fetch_failures']} fetch failures — missed announcements "
                    "bias the sample toward quiet periods")
    if sample.get("n_companies", 0) <= 3 and n > 0:
        fake.append("one-company dependence — not general evidence")
    by_type = sample.get("by_type", {})
    if by_type and max(by_type.values()) / max(n, 1) >= 0.8:
        fake.append("event-category concentration — one type dominates")
    if sample.get("top_event_share", 0) >= 0.5:
        fake.append("one single event dominates the economics")
    if (coverage or {}).get("abstentions", 0) > n:
        fake.append("abstentions exceed events — pipeline mostly blind")
    if economics is None:
        fake.append("no economics measured yet — classification quality proves nothing (§86)")

    concentration = None
    if sample.get("per_event_pnl"):
        concentration = CONC.analyze(
            [{"id": e["event_id"], "pnl": e["pnl"],
              "sector": e.get("event_type", "UNKNOWN")} for e in sample["per_event_pnl"]])

    verdict = sample.get("verdict_hint") or (
        "EVENT_FORWARD_INFANCY" if n < 30 else "FORWARD_PENDING")
    return {
        "why_fake": fake,
        "sample": sample,
        "economics": economics or {"missing": "no economics measured"},
        "coverage": coverage or {"missing": "no coverage report"},
        "concentration": concentration or {"missing": "no per-event pnl"},
        "verdict": verdict,
        "missing_evidence": [k for k, v in
                             {"economics": economics, "coverage": coverage}.items()
                             if v is None],
        "note": "failure-first (§67): fake-reasons precede any benefit claim",
    }
