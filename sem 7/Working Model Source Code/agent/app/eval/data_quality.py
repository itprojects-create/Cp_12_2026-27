"""Data-quality gates: score every experiment's inputs (§35).

Fields: coverage, missingness, timestamp_quality, PIT_confidence, staleness,
source_reliability, corporate_action_quality, membership_quality — each in
[0,1]. Strategies leaning on poor-quality data are rejected or downgraded.
Verdict: PASS (>=0.75), FLAG (>=0.5), REJECT (<0.5). PIT_confidence < 0.5 alone
forces REJECT (promotion requires PIT certainty).
"""
from __future__ import annotations

FIELDS = ("coverage", "missingness_good", "timestamp_quality", "pit_confidence",
          "freshness", "source_reliability", "corporate_action_quality",
          "membership_quality")

# cost inputs arrive as missingness (badness); the gate works in goodness units.
WEIGHTS = {"coverage": 2.0, "missingness_good": 2.0, "timestamp_quality": 1.0,
           "pit_confidence": 3.0, "freshness": 1.0, "source_reliability": 1.0,
           "corporate_action_quality": 1.0, "membership_quality": 2.0}


def assess(missingness: float = 0.0, coverage: float = 1.0,
           timestamp_quality: float = 1.0, pit_confidence: float = 1.0,
           freshness: float = 1.0, source_reliability: float = 1.0,
           corporate_action_quality: float = 1.0,
           membership_quality: float = 1.0) -> dict:
    vals = {"coverage": coverage, "missingness_good": 1.0 - missingness,
            "timestamp_quality": timestamp_quality, "pit_confidence": pit_confidence,
            "freshness": freshness, "source_reliability": source_reliability,
            "corporate_action_quality": corporate_action_quality,
            "membership_quality": membership_quality}
    for k, v in vals.items():
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"data-quality {k} must be in [0,1], got {v}")
    total_w = sum(WEIGHTS.values())
    score = sum(vals[k] * WEIGHTS[k] for k in FIELDS) / total_w
    if vals["pit_confidence"] < 0.5:
        verdict = "REJECT"
        reason = "PIT confidence below 0.5 — promotion requires PIT certainty"
    elif score >= 0.75:
        verdict, reason = "PASS", "inputs adequate"
    elif score >= 0.5:
        verdict, reason = "FLAG", "downgraded: weak inputs, needs corroboration"
    else:
        verdict, reason = "REJECT", "inputs too poor to support any claim"
    worst = min(vals, key=vals.get)
    if vals[worst] < 0.5 and verdict == "PASS":
        # No single input leg may be majority-bad inside a PASS: a strategy
        # leaning on one poor-quality feed is downgraded even when the average
        # looks fine.
        verdict = "FLAG"
        reason = f"downgraded: {worst}={vals[worst]:.2f} below 0.5"
    return {"score": round(score, 4), "verdict": verdict, "reason": reason,
            "fields": {k: round(v, 4) for k, v in vals.items()}}
