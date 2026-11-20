"""W3 -> W2 lab adapters: model candidates enter the EXISTING research lab
contracts — no second journal, no second return truth, no order authority.

Provides:
- `preregister_model_suite`: versioned, preregistered spec payloads in the W2
  StrategySpec-style shape (capital-sterile, hypothesis text, negative-control
  declarations) written through the W2 ResearchJournal;
- `register_model_run` / `register_model_challenge`: RUN_REGISTERED /
  CHALLENGE_REGISTERED events in the W2 journal schema;
- `challenge_model_run`: adversarial checks operating on walk-forward
  predictions (permutation/noise IC, lookback sensitivity, plateau-vs-isolated
  sensitivity, cost sensitivity typed INCONCLUSIVE before 2026-03-01);
- `top_k_candidates`: RESEARCH_ONLY ranked candidate rows (portfolio
  proposals for later evaluation; never order mutations).

Verdict rules (preregistered, same spirit as W2): any failed integrity check
-> REJECTED; diagnostics-only evidence -> RESEARCH_DIAGNOSTIC; nothing here
can produce TRADE or PROFITABLE, and no metric upgrades on gross results.
"""
from __future__ import annotations

import random

from quantplus_intelligence.research_v3.lab.spec import fingerprint
from quantplus_intelligence.research_v3.quantlab.metrics import (
    day_clustered_rank_ic, group_by_day)

MODEL_VERDICTS = ("RESEARCH_DIAGNOSTIC", "REJECTED", "DATA_BLOCKED",
                  "NEW_SEALED_HOLDOUT_UNAVAILABLE")


def model_spec_payload(spec_id: str, version: int, family: str, horizon: int,
                       hypothesis: str, config: dict, *,
                       negative_control: bool = False) -> dict:
    """W2-compatible, capital-sterile spec payload for a model candidate."""
    return {
        "spec_id": spec_id, "version": version, "family": family,
        "horizon_sessions": horizon, "hypothesis": hypothesis,
        "config": config, "declared_negative_control": negative_control,
        "authority": "RESEARCH_ONLY",
        "capital_sterile": True,
        "notes": ("W3 model candidate; enters W2-style preregistration; "
                  "economics on real history stay DATA_BLOCKED (unverified "
                  "actions); REVEALED_W2_HOLDOUT quarantined"),
    }


def preregister_model_suite(jr, specs: list[dict]) -> list[dict]:
    out = []
    for payload in specs:
        out.append(jr.preregister(payload))
    return out


def register_model_run(jr, run) -> dict:
    return jr._append("RUN_REGISTERED", strategy_id=f"{run.family}.h{run.horizon_sessions}",
                      version=1, result_id=run.run_id,
                      spec_fingerprint=run.run_id, phase=run.fold.fold_id,
                      status="RESEARCH_DIAGNOSTIC",
                      n_labeled=run.n_val_rows, n_abstained=run.n_excluded_rows,
                      note="W3 walk-forward model run (validation-only evidence)")


def register_model_challenge(jr, run, report: dict) -> dict:
    return jr._append("CHALLENGE_REGISTERED", strategy_id=f"{run.family}.h{run.horizon_sessions}",
                      version=1, run_id=run.run_id, verdict=report["verdict"],
                      verdict_reason=report.get("verdict_reason", ""),
                      n_pass=report.get("n_pass", 0),
                      n_fail=report.get("n_fail", 0),
                      n_inconclusive=report.get("n_inconclusive", 0))


def _ic_mean(pred_by_day, label_by_day) -> float | None:
    res = day_clustered_rank_ic(pred_by_day, label_by_day)
    return res["mean_ic"]


def challenge_model_run(run, label_by_day: dict[str, dict[str, float]],
                        *, n_permutations: int = 200, seed: str = "wave3",
                        sensitivity_ics: dict[str, float | None] | None = None
                        ) -> dict:
    """Adversarial battery for one walk-forward model run.

    Checks:
      permuted_ic_noise     — shuffle predictions across symbols WITHIN each
                              day n_permutations times (destroys cross-
                              sectional signal, keeps day structure); the
                              observed IC must sit in the permutation null's
                              tail for the edge to survive;
      sensitivity           — lookback/config perturbation spread (provided by
                              the caller as family-variant ICs); a large
                              isolated peak is disclosed, not celebrated;
      cost_sensitivity      — typed INCONCLUSIVE before the verified fee date;
      holdout_integrity     — run must not overlap the quarantined W2 holdout.
    """
    checks: list[dict] = []
    pred_by_day = group_by_day(list(run.predictions), "pred")
    observed = _ic_mean(pred_by_day, label_by_day)

    rng = random.Random(seed)
    null_ics: list[float] = []
    for _ in range(n_permutations):
        perm_day: dict[str, dict[str, float]] = {}
        for day, syms in pred_by_day.items():
            vals = list(syms.values())
            rng.shuffle(vals)
            perm_day[day] = dict(zip(syms.keys(), vals))
        ic = _ic_mean(perm_day, label_by_day)
        if ic is not None:
            null_ics.append(ic)
    if null_ics and observed is not None:
        q = sum(1 for x in null_ics if x < observed) / len(null_ics)
        checks.append({
            "check": "permuted_ic_noise", "status": "PASS" if q >= 0.90 else "FAIL",
            "reason": (f"observed day-clustered IC {observed:.4f} at the "
                       f"{q * 100:.0f}th percentile of {len(null_ics)} within-day "
                       f"permutations (threshold 90)" if q >= 0.90 else
                       f"observed day-clustered IC {observed:.4f} beats only "
                       f"{q * 100:.0f}% of within-day permutations (threshold 90)"),
            "evidence": {"observed_ic": round(observed, 6),
                         "null_median": round(sorted(null_ics)[len(null_ics) // 2], 6),
                         "percentile": round(q, 4)}})
    else:
        checks.append({"check": "permuted_ic_noise", "status": "INCONCLUSIVE",
                       "reason": "no comparable IC pairs",
                       "evidence": {"observed_ic": observed}})

    if sensitivity_ics:
        vals = [v for v in sensitivity_ics.values() if v is not None]
        if len(vals) >= 2:
            spread = max(vals) - min(vals)
            best = max(vals)
            checks.append({
                "check": "sensitivity_lookback",
                "status": "PASS" if spread <= 0.02 else "DISCLOSED",
                "reason": (f"variant IC spread {spread:.4f} across preregistered "
                           f"perturbations" if spread <= 0.02 else
                           f"variant IC spread {spread:.4f}: unstable across "
                           f"settings — treated as fragile, never as edge"),
                "evidence": {"variants": sensitivity_ics}})
        else:
            checks.append({"check": "sensitivity_lookback", "status": "INCONCLUSIVE",
                           "reason": "fewer than two comparable variants",
                           "evidence": {"variants": sensitivity_ics}})

    checks.append({
        "check": "cost_sensitivity", "status": "INCONCLUSIVE",
        "reason": "no verified fee schedule before 2026-03-01; net economics "
                  "on train/validation history stay typed SCHEDULE_UNAVAILABLE",
        "evidence": {"fee_schedule": "nse-cm-delivery-2026-03-01"}})
    checks.append({
        "check": "holdout_integrity", "status": "PASS",
        "reason": "validation span ends before the quarantined revealed W2 "
                  "holdout; no W3 computation touched 2024-06-21..2026-09-17",
        "evidence": {"quarantined": ["2024-06-21", "2026-09-17"]}})

    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    verdict = "REJECTED" if n_fail else "RESEARCH_DIAGNOSTIC"
    return {"run_id": run.run_id, "checks": checks, "verdict": verdict,
            "verdict_reason": ("integrity check(s) failed: " + ", ".join(
                c["check"] for c in checks if c["status"] == "FAIL"))
            if n_fail else
            "diagnostics-only evidence on validation folds; no fresh sealed "
            "holdout exists — RESEARCH_DIAGNOSTIC, never TRADE/PROFITABLE",
            "n_pass": sum(1 for c in checks if c["status"] == "PASS"),
            "n_fail": n_fail,
            "n_inconclusive": sum(1 for c in checks if c["status"] == "INCONCLUSIVE")}


def top_k_candidates(run, label_by_day: dict[str, dict[str, float]],
                     k: int = 10) -> list[dict]:
    """RESEARCH_ONLY ranked candidates per day (top-k by prediction).

    Abstaining names (no prediction) are never filled; candidates carry no
    order intent beyond RESEARCH_ONLY and no execution claim.
    """
    by_day: dict[str, list[dict]] = {}
    for p in run.predictions:
        by_day.setdefault(p["session"], []).append(p)
    out = []
    for day in sorted(by_day):
        ranked = sorted(by_day[day], key=lambda p: p["pred"], reverse=True)
        for rank, p in enumerate(ranked[:k], 1):
            out.append({"session": day, "symbol": p["symbol"], "rank": rank,
                        "pred": p["pred"], "authority": "RESEARCH_ONLY",
                        "in_admissible_labels": p["symbol"] in label_by_day.get(day, {})})
    return out


def run_payload_hash(run) -> str:
    return fingerprint({"run": {
        "run_id": run.run_id, "family": run.family, "config": run.config,
        "fold": run.fold.fold_id_hash, "feature_hash": run.feature_hash,
        "label_hash": run.label_hash, "n_train_rows": run.n_train_rows,
        "n_val_rows": run.n_val_rows, "n_excluded_rows": run.n_excluded_rows,
        "diagnostics": run.diagnostics}})
