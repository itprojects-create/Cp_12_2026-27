"""Evidence-class-aware promotion gates (P4, §§31–38, 47–51).

ALPHA uses the existing GATESET_V1 unchanged. RISK/EXECUTION/DATA_QUALITY have
their own frozen gatesets with class-appropriate success criteria — a risk
control is NEVER rejected solely for lower CAGR (§32), and an alpha candidate
can NEVER pass on risk-only improvement. UNIVERSE candidates route through the
DATA_QUALITY gateset (PIT correctness / investability evidence).

Verdict vocabulary (§38, compatible with StrategyStatus): ALPHA_PASS,
RISK_PASS, EXECUTION_PASS, QUALITY_PASS, NO_ECONOMIC_VALUE,
INSUFFICIENT_DATA, FORWARD_PENDING, KILLED.
"""
from __future__ import annotations

from app.evo import promotion as ALPHA_GATES
from app.governance import constitution as C

RISK_VERSION = "RISK_GATESET_V1"
EXEC_VERSION = "EXEC_GATESET_V1"
QUALITY_VERSION = "DATAQUALITY_GATESET_V1"

# RISK_GATESET_V1 bars (documented rationale per bar):
MIN_RISK_EVENTS = 30  # same infancy floor as the experiment manifest
MIN_RISK_COMPANIES = 10
MIN_RISK_EVENT_DAYS = 20
MIN_CVAR_IMPROVEMENT = 0.001  # 10bps/day tail improvement — modest, must be strict >0
MAX_OPPORTUNITY_DRAG = 0.02  # risk control may cost at most 2pp total return
MAX_ADDED_COST = 0.005  # 50bps cost budget for the control itself
MAX_MAXDD_SLACK = 0.02  # drawdown must not worsen beyond slack (catastrophic guard)


def check_risk(evidence: dict, gateset: str = RISK_VERSION) -> dict:
    if gateset != RISK_VERSION:
        raise ValueError(f"unknown risk gateset {gateset!r}")
    failures, warnings = [], []
    if not evidence.get("pit_safe", False):
        failures.append("pit_safe is not True")
    if not evidence.get("no_leakage_attested", False):
        failures.append("leakage attestation missing")
    if not C.promotion_eligible_dataset(evidence.get("dataset", "")):
        failures.append("not forward-only evidence (R6/R7/R8)")
    sample = evidence.get("sample", {})
    if (sample.get("n_events", 0) < MIN_RISK_EVENTS
            or sample.get("n_companies", 0) < MIN_RISK_COMPANIES
            or sample.get("n_event_days", 0) < MIN_RISK_EVENT_DAYS):
        return {"eligible": False, "verdict": "FORWARD_PENDING",
                "failures": [f"infancy: {sample} below 30/10/20 minimums"],
                "warnings": warnings, "gateset": gateset}
    risk = evidence.get("risk", {})
    missing = [k for k in ("candidate_cvar95", "control_cvar95", "candidate_maxdd",
                           "control_maxdd", "opportunity_drag", "added_cost",
                           "candidate_max_event_loss", "control_max_event_loss")
               if k not in risk]
    if missing:
        return {"eligible": False, "verdict": "INSUFFICIENT_DATA",
                "failures": [f"risk block missing {missing}"], "warnings": warnings,
                "gateset": gateset}
    cvar_gain = risk["candidate_cvar95"] - risk["control_cvar95"]
    if cvar_gain < MIN_CVAR_IMPROVEMENT:
        failures.append(f"tail not improved: CVaR95 gain {cvar_gain:.4f} < 0.001")
    if risk["candidate_max_event_loss"] < risk["control_max_event_loss"]:
        failures.append("catastrophic risk increased: worst event loss worse than control")
    if risk["candidate_maxdd"] - risk["control_maxdd"] > MAX_MAXDD_SLACK:
        failures.append("drawdown worse than control beyond 2pp slack")
    if risk["opportunity_drag"] > MAX_OPPORTUNITY_DRAG:
        failures.append(f"opportunity drag {risk['opportunity_drag']:.4f} > 2pp bound")
    if risk["added_cost"] > MAX_ADDED_COST:
        failures.append("control costs more than 50bps to operate")
    if evidence.get("data_quality", {}).get("verdict") == "REJECT":
        failures.append("data-quality REJECT (§87: good PnL + bad lineage = FAIL)")
    dq = evidence.get("data_quality")
    if dq is None:
        warnings.append("data-quality unassessed")
    if evidence.get("concentration", {}).get("single_name_dependent"):
        warnings.append("single-name dependent — tail win may be one event (§68)")
    if not failures and (cvar_gain <= 0 and risk["opportunity_drag"] >= 0):
        return {"eligible": False, "verdict": "NO_ECONOMIC_VALUE",
                "failures": ["no tail improvement and no opportunity saving"],
                "warnings": warnings, "gateset": gateset}
    verdict = "RISK_PASS" if not failures else "KILLED"
    return {"eligible": not failures, "verdict": verdict, "failures": failures,
            "warnings": warnings, "gateset": gateset}


def check_execution(evidence: dict, gateset: str = EXEC_VERSION) -> dict:
    if gateset != EXEC_VERSION:
        raise ValueError(f"unknown execution gateset {gateset!r}")
    failures, warnings = [], []
    if not evidence.get("pit_safe", False):
        failures.append("pit_safe is not True")
    if not C.promotion_eligible_dataset(evidence.get("dataset", "")):
        failures.append("not forward-only evidence")
    exe = evidence.get("execution", {})
    if exe.get("n", 0) < 60:
        return {"eligible": False, "verdict": "FORWARD_PENDING",
                "failures": ["infancy: n<60"], "warnings": warnings, "gateset": gateset}
    if exe.get("cost_improvement", 0) <= 0 and exe.get("turnover_reduction", 0) <= 0:
        failures.append("no execution improvement (cost or turnover)")
    if exe.get("strategy_degradation", 0) < -0.005:
        failures.append("material strategy degradation beyond 50bps")
    verdict = "EXECUTION_PASS" if not failures else "KILLED"
    return {"eligible": not failures, "verdict": verdict, "failures": failures,
            "warnings": warnings, "gateset": gateset}


def check_quality(evidence: dict, gateset: str = QUALITY_VERSION) -> dict:
    if gateset != QUALITY_VERSION:
        raise ValueError(f"unknown quality gateset {gateset!r}")
    failures = []
    dq = evidence.get("data_quality_delta", {})
    if not dq:
        return {"eligible": False, "verdict": "INSUFFICIENT_DATA",
                "failures": ["no before/after quality comparison"], "warnings": [],
                "gateset": gateset}
    for k in ("coverage_delta", "pit_confidence_delta"):
        if dq.get(k, 0) <= 0:
            failures.append(f"{k} not improved (CAGR-neutral by design, §51)")
    if dq.get("mismatch_rate", 1) != 0:
        failures.append("correctness failures remain (mismatch rate != 0)")
    verdict = "QUALITY_PASS" if not failures else "KILLED"
    return {"eligible": not failures, "verdict": verdict, "failures": failures,
            "warnings": [], "gateset": gateset}


def check_by_class(evidence_class: str, evidence: dict) -> dict:
    """Dispatch to the class gateset. ALPHA reuses frozen GATESET_V1 (unweakened);
    UNIVERSE routes to quality gates (PIT correctness evidence)."""
    if evidence_class == "ALPHA":
        gate = ALPHA_GATES.check(evidence)
        verdict = "ALPHA_PASS" if gate["eligible"] else (
            "FORWARD_PENDING" if any("INFANCY" in f for f in gate["failures"])
            else "KILLED")
        return {**gate, "verdict": verdict}
    if evidence_class == "RISK_CONTROL":
        return check_risk(evidence)
    if evidence_class == "EXECUTION":
        return check_execution(evidence)
    if evidence_class in ("UNIVERSE", "DATA_QUALITY"):
        return check_quality(evidence)
    raise ValueError(f"unknown evidence class {evidence_class!r}")
