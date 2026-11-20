"""Friction matrix: every cost cell modeled|partial|unmodeled + estimate-or-reason (prereg §5).

Estimates marked MEASURED come from paper ledgers; BOUND from arithmetic caps;
ASSUMED is labeled with its assumption. Unmodeled cells stay visible — the
matrix is the opposite of burying them.
"""
from __future__ import annotations

# status, estimate_rupees_on_10L_narrow (or bound/reason), basis
CELLS: tuple[tuple[str, str, str, str], ...] = (
    ("brokerage", "modeled", "~44,008 (in tier costs)",
     "MEASURED: paper_10L_nifty50.json costs_rupees (0.105%/side large-cap)"),
    ("STT", "partial", "bundled inside tier rates (delivery 0.10%/side ≈ covered)",
     "Not itemized separately; tier rates calibrated to include it"),
    ("stamp duty", "unmodeled", "≤0.015% × gross traded ≈ ≤₹2,500 on narrow book",
     "BOUND: 0.015% delivery rate × gross traded implied by 44k costs"),
    ("GST + SEBI + exchange charges", "unmodeled", "~0.02% all-in, ≈ ₹2-3k lifetime",
     "BOUND: statutory schedule on turnover"),
    ("spread large-cap", "modeled", "in 0.105%/side tier",
     "MEASURED via tier costs"),
    ("spread SME", "modeled", "1.50%/side tier (1–3% observed spreads)",
     "ASSUMED rate, labeled in prereg_day1_environment.md"),
    ("circuit non-fills", "modeled", "locks_hit=0 on narrow (measured, Day-1 run)",
     "MEASURED: Day-1 honest-env replay defers fills, books no cost"),
    ("token inference", "modeled", "₹156,465 lifetime ledger (43% of paper profit)",
     "MEASURED: usage_daily × ASSUMED Rs.9/1K (Day-1 env report)"),
    ("slippage beyond spread", "unmodeled", "order size ≪ ADT (top-50 liquid names)",
     "Reason: weekly rebalance, small-vs-volume; bound deferred to AngelOne paper"),
    ("latency", "n/a", "weekly rebalance — execution timing immaterial",
     "Reason: 5-day hold horizon dominates seconds of delay"),
    ("corporate-action timing", "partial", "adjusted closes (split timing approx)",
     "Disclosed approx in every paper report"),
    ("survivorship", "unmodeled-bias", "direction UP, magnitude unquantified",
     "CONFIRMED: verification report Part B (5 disaster names absent)"),
    ("model-level LLM leakage", "n/a-deterministic",
     "core immune by construction (zero LLM in money path); agent evals ran "
     "pre-cutoff scenarios through post-cutoff models (contamination IN the "
     "LLM's favor) and still failed — stronger null",
     "Reason + evidence: grep-clean core; H1/retry FAILs on record"),
)


def matrix() -> list[dict]:
    return [{"cell": c, "status": s, "estimate": e, "basis": b} for c, s, e, b in CELLS]


def modeled_count() -> dict:
    m = matrix()
    return {"modeled": sum(1 for r in m if r["status"] == "modeled"),
            "partial": sum(1 for r in m if r["status"] == "partial"),
            "unmodeled": sum(1 for r in m if "unmodeled" in r["status"]),
            "na_with_reason": sum(1 for r in m if r["status"].startswith("n/a")),
            "total": len(m)}
