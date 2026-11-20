"""Versioned promotion gates (migration §18).

GATESET_V1: the first promotion gateset. Bars are documented, conservative,
and kill-favoring (§16: a missed strategy is cheaper than fake alpha).
Thresholds are frozen per version — a new philosophy means a new version +
prereg, never a silent edit. The frozen 2026-09-18 direction gates are reused
by reference (GATESET_FROZEN_20260918), not duplicated.
"""
from __future__ import annotations

from app.governance import constitution as C

VERSION = "GATESET_V1"

# Documented bars (all must hold; see module docstring for rationale).
MIN_FORWARD_N = 60  # mirrors evo MIN_DECISIONS: infancy is not evidence (§31)
MAX_MAXDD_SLACK = 0.02  # challenger MaxDD may trail champion by at most 2pp
MAX_TOP1_SHARE = 0.50  # concentration kill line (matches concentration heuristic)
MIN_DSR = 0.50  # matches the Day-5 narrow null bar (0.52); below = warning only


def check(evidence: dict, gateset: str = VERSION) -> dict:
    """Evaluate a challenger evidence pack. Returns
    {eligible, failures[], warnings[], gateset}. Pure function, no I/O."""
    if gateset != VERSION:
        raise ValueError(f"unknown gateset {gateset!r} (available: {VERSION})")
    failures: list[str] = []
    warnings: list[str] = []
    inc = evidence.get("incremental_alpha", {})
    conc = evidence.get("concentration", {})
    if not evidence.get("pit_safe", False):
        failures.append("pit_safe is not True (PIT_REQUIRED_FOR_PROMOTION)")
    if not evidence.get("no_leakage_attested", False):
        failures.append("leakage attestation missing")
    dataset = evidence.get("dataset", "")
    if not C.promotion_eligible_dataset(dataset):
        failures.append(f"dataset {dataset!r} is not forward-only evidence (R6/R7/R8)")
    n = int(inc.get("n", 0))
    if n < MIN_FORWARD_N:
        failures.append(f"forward sample n={n} < {MIN_FORWARD_N} (INFANCY, §31)")
    if not inc or inc.get("insufficient_data"):
        failures.append("incremental-alpha block missing or insufficient")
    else:
        if not inc.get("estimated_alpha", 0) > 0:
            failures.append("incremental alpha <= 0 vs champion/benchmark")
        if inc.get("incremental_sharpe", 0) < 0:
            failures.append("incremental Sharpe < 0 vs champion")
        if inc.get("incremental_maxdd", 0) > MAX_MAXDD_SLACK:
            failures.append("drawdown worse than champion beyond 2pp slack")
        if "incremental_cost" not in inc:
            failures.append("incremental cost undocumented (R11)")
    if not conc or "top_1_share" not in conc:
        failures.append("concentration block missing (§12)")
    elif conc["top_1_share"] >= MAX_TOP1_SHARE:
        failures.append(f"top-1 share {conc['top_1_share']:.0%} >= 50% (lucky-stock, §12)")
    dsr = evidence.get("dsr")
    if dsr is None:
        warnings.append("DSR missing — required before champion tenure extends")
    elif dsr < MIN_DSR:
        warnings.append(f"DSR {dsr} below {MIN_DSR}")
    if evidence.get("pbo") is None and evidence.get("pbo_lite") is None:
        warnings.append("PBO/PBO-lite missing")
    if evidence.get("placebo") is None:
        warnings.append("placebo/randomization missing (§20)")
    if evidence.get("stability") is None:
        warnings.append("parameter stability missing (§19)")
    if evidence.get("data_quality", {}).get("verdict") == "REJECT":
        failures.append("data-quality REJECT (§35)")
    return {"eligible": not failures, "failures": failures,
            "warnings": warnings, "gateset": gateset}
