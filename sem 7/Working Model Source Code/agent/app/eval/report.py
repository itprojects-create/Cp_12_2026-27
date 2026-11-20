"""Failure-first candidate report: WHY THIS COULD BE FAKE before WHY IT COULD WORK (§36).

Assembles incremental-alpha, benchmark, concentration, LOO, regime, placebo,
stability, and data-quality outputs into one ordered structure. Weaknesses
first, verdict last, missing-evidence list always present.
"""
from __future__ import annotations

from app.eval import benchmarks as BM
from app.eval import concentration as CONC
from app.eval import data_quality as DQ
from app.eval import incremental_alpha as IA
from app.eval import loo as LOO
from app.eval import placebo as PLA
from app.eval import regimes as REG
from app.eval import stability as STAB


def summarize_candidate(candidate_daily: list[float], champion_daily: list[float],
                        benchmark_daily: list[float],
                        contributions: list[dict] | None = None,
                        regime_labels: dict[int, str] | None = None,
                        stability_grid: tuple[list, dict] | None = None,
                        null_metrics: list[float] | None = None,
                        true_metric: float | None = None,
                        data_quality: dict | None = None,
                        known_weaknesses: list[str] | None = None,
                        falsification_results: list[str] | None = None) -> dict:
    """All series are aligned daily net returns. Contributions/regimes/optional
    blocks attach when supplied; absent blocks are recorded as missing (§53)."""
    inc = IA.evaluate(candidate_daily, champion_daily, benchmark_daily)
    bench = BM.attribute(candidate_daily, benchmark_daily)
    weaknesses: list[str] = list(known_weaknesses or [])
    if inc.get("insufficient_data"):
        weaknesses.append("insufficient return history for any return claim")
    if inc.get("alpha_low_confidence"):
        weaknesses.append(f"regression alpha on n={inc.get('n')} — low confidence, do not overstate")
    if bench.get("beta", 0) and abs(bench["beta"]) > 0.8:
        weaknesses.append(f"beta {bench['beta']:.2f} explains most movement — alpha claim is beta in disguise")

    blocks: dict = {"incremental_alpha": inc, "benchmark": bench}
    if contributions is not None:
        conc = CONC.analyze(contributions)
        blocks["concentration"] = conc
        loo_top = LOO.leave_top_contributor_out(contributions)
        blocks["leave_top_out"] = loo_top
        if conc.get("single_name_dependent"):
            weaknesses.append(f"single-name dependent: top-1 share {conc['top_1_share']:.0%}")
        if conc.get("narrow_base"):
            weaknesses.append(f"narrow base: top-5 share {conc['top_5_share']:.0%}")
    else:
        blocks["concentration"] = {"missing": "no contribution data supplied"}
        weaknesses.append("concentration unknown — no contribution data")
    if regime_labels is not None:
        reg = REG.analyze(candidate_daily, regime_labels)
        dep = REG.regime_dependence(reg)
        blocks["regimes"] = {**reg, "dependence": dep}
        if dep.get("best_share", 0) and dep["best_share"] >= 0.80:
            weaknesses.append(f"regime-bound: {dep['best_share']:.0%} in {dep['best_regime']}")
    else:
        blocks["regimes"] = {"missing": "no regime labels supplied"}
    if stability_grid is not None:
        grid, metrics = stability_grid
        stab = STAB.analyze(grid, metrics)
        blocks["stability"] = stab
        if stab.get("isolated_peak"):
            weaknesses.append(f"isolated parameter peak at {stab['best']} — suspicious (§19)")
    else:
        blocks["stability"] = {"missing": "no parameter grid supplied"}
    if null_metrics is not None and true_metric is not None:
        blocks["placebo"] = PLA.permutation_pvalue(true_metric, null_metrics)
        if blocks["placebo"]["p_value"] >= 0.10:
            weaknesses.append(f"placebo p={blocks['placebo']['p_value']} — cannot beat chance")
    else:
        blocks["placebo"] = {"missing": "no null distribution supplied"}
    if data_quality is not None:
        blocks["data_quality"] = data_quality
        if data_quality.get("verdict") == "REJECT":
            weaknesses.append("data quality REJECT: " + str(data_quality.get("reason")))
    else:
        blocks["data_quality"] = {"missing": "no data-quality assessment supplied"}
        weaknesses.append("data quality unknown")

    missing_evidence = [k for k, v in blocks.items()
                        if isinstance(v, dict) and "missing" in v]
    verdict = ("REJECT" if any(w.startswith(("single-name dependent", "data quality REJECT",
                                             "insufficient return"))
                               for w in weaknesses)
               else ("WEAK" if weaknesses else "SURVIVES_SO_FAR"))
    return {"why_fake": weaknesses, "blocks": blocks,
            "falsification_results": falsification_results or [],
            "missing_evidence": missing_evidence, "verdict": verdict,
            "note": "failure-first: weaknesses precede any performance claim (§36)"}
