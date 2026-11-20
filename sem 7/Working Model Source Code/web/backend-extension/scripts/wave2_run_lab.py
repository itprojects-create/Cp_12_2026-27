"""W2 orchestration: seal -> preregister -> run -> sweep -> challenge -> reveal
-> holdout -> artifacts. Deterministic, read-only, paper-only.

Research-plane only (W1 precedent): the runtime app is never imported. The
runner reuses the exact W0 fee model and the W1 warehouse; the sealed holdout
is structurally unreachable from sweeps; negative controls are preregistered
and can never earn promotion.

Outputs (reports/alpha_v3_1/):
  wave2_research_journal.jsonl      append-only hash-chained event log
  wave2_preregistered_specs.json    pinned specs + fingerprints
  wave2_backtest_results.json       immutable BacktestResult payloads
  wave2_parameter_sweep.csv         every tried variant (incl. failures)
  wave2_challenge_report.json       per-run adversarial battery + comparisons
  wave2_holdout_registry.json       journal status per spec version
  wave2_data_coverage.json          list_data_coverage for both windows
  wave2_artifacts_manifest.json     sha256 of every artifact above
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.lab import (
    ExecutionSpec, PitPanel, ResearchJournal, SignalSpec, SpecError,
    StrategySpec, UniverseSpec, WindowSpec, challenge_finding, compare_runs,
    list_data_coverage, run_backtest, run_cost_scenarios, run_sweep)
from quantplus_intelligence.research_v3.lab.journal import require_sealed
from quantplus_intelligence.research_v3.lab.spec import fingerprint

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "alpha_v3_1"
# Explicit warehouse path (W1 pattern): DEFAULT_DB resolves one directory too
# high in the dev repo and silently creates an empty DB.
DB = ROOT / "backend-extension" / "data" / "research_v3" / "warehouse.sqlite3"
assert DB.is_file(), f"warehouse missing: {DB}"
WINDOWS = ("2015-06-01", "2021-12-31", "2022-01-01", "2023-12-31",
           "2024-06-21", "2026-09-17")
CAPITAL = 10_000_000          # Rs 1,00,000 in paise
BPS = 10                      # adverse integer-paise slippage scenario

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def build_specs() -> dict[str, StrategySpec]:
    w = WindowSpec(*WINDOWS)
    common = dict(universe=UniverseSpec(), execution=ExecutionSpec(
        capital_paise=CAPITAL, slippage_bps=BPS), windows=w)
    return {
        "wave2.h1.momentum-6m": StrategySpec(
            spec_id="wave2.h1.momentum-6m", version=1,
            hypothesis=("H1: cross-sectional 6-month (126-session) price "
                        "momentum, top-10 equal weight, monthly rebalance at "
                        "the executable open; long-only NIFTY50 as-of members"),
            signal=SignalSpec("cross_sectional_momentum", lookback_sessions=126,
                              top_k=10),
            notes=("sector-relative variant is DATA_BLOCKED: no verified "
                   "historical sector map is ingested; raw/unadjusted bars "
                   "mean economics vs TRI stays blocked until actions verify"),
            **common),
        "wave2.h2.near-52w-high": StrategySpec(
            spec_id="wave2.h2.near-52w-high", version=1,
            hypothesis=("H2: 52-week-high continuation, long the 10 names "
                        "closest to their 252-session available high, equal "
                        "weight, monthly rebalance at the executable open"),
            signal=SignalSpec("near_52w_high", high_window_sessions=252,
                              top_k=10),
            notes="never a 65-bar proxy: the window is 252 available sessions",
            **common),
        "wave2.baseline.equal-weight": StrategySpec(
            spec_id="wave2.baseline.equal-weight", version=1,
            hypothesis=("Control baseline: equal weight across ALL eligible "
                        "as-of members (ranking-neutral portfolio), identical "
                        "windows, execution and fee model"),
            signal=SignalSpec("cross_sectional_momentum", lookback_sessions=126,
                              top_k=50),
            notes="top_k = universe size: momentum ranking selects everyone",
            **common),
        "wave2.control.leak.same-day-close": StrategySpec(
            spec_id="wave2.control.leak.same-day-close", version=1,
            hypothesis=("Deliberate negative control: ranks by the decision "
                        "session's close, a bar whose available_at exceeds "
                        "the decision cutoff; must be caught and rejected"),
            signal=SignalSpec("leak_control", lookback_sessions=126, top_k=10),
            declared_negative_control=True, **common),
        "wave2.control.noise.seeded": StrategySpec(
            spec_id="wave2.control.noise.seeded", version=1,
            hypothesis=("Deliberate negative control: seeded random portfolio "
                        "from the same eligible pools; must earn no edge"),
            signal=SignalSpec("noise_control", lookback_sessions=126, top_k=10),
            declared_negative_control=True, **common),
    }


def ensure_seal(jr: ResearchJournal, sid: str, ver: int) -> None:
    if jr.seal_record(sid, ver) is None:
        jr.seal_holdout(sid, ver, (WINDOWS[4], WINDOWS[5]))
        log(f"sealed holdout for {sid} v{ver}")


def ensure_prereg(jr: ResearchJournal, spec: StrategySpec) -> None:
    fps = {e["spec_fingerprint"] for e in jr.entries_for(spec.spec_id, spec.version)
           if e["event"] == "SPEC_PREREGISTERED"}
    if spec.fingerprint() not in fps:
        jr.preregister(spec.to_payload())


def main() -> None:
    conn = W.connect(str(DB))
    REPORTS.mkdir(parents=True, exist_ok=True)
    jr = ResearchJournal(str(REPORTS / "wave2_research_journal.jsonl"))
    specs = build_specs()
    for sid, spec in specs.items():
        ensure_seal(jr, sid, spec.version)
        ensure_prereg(jr, spec)
    seal = require_sealed(jr, "wave2.h1.momentum-6m", 1)
    seal_info = {"sealed_before_runs": True, "sealed_at": seal["ts"],
                 "window": seal["window"], "journal": str(jr.path)}
    log("holdout sealed + specs preregistered")

    panel = PitPanel(conn, "nifty50")
    log(f"panel built: {len(panel.series)} spell symbols, "
        f"{len(panel.sessions)} sessions")

    results: dict[str, object] = {}
    log("phase: train_validation runs")
    for sid, spec in specs.items():
        res = run_backtest(spec, conn=conn, panel=panel, phase="train_validation")
        results[sid] = res
        jr.register_run(res)
        labeled = sum(1 for m in res.months if m["gross_month"] is not None)
        log(f"  {sid}: status={res.status} labeled={labeled} "
            f"abstained={len(res.abstained_months)}")

    log("phase: bounded sweeps (train+validation only; holdout unreachable)")
    sweeps = {}
    sweep_grid_h1 = {"lookback_sessions": [63, 126, 189, 252],
                     "skip_sessions": [0, 21], "top_k": [10, 20]}
    sweep_grid_h2 = {"high_window_sessions": [189, 252], "top_k": [10, 20]}
    sweeps["wave2.h1.momentum-6m"] = run_sweep(specs["wave2.h1.momentum-6m"],
                                               sweep_grid_h1, conn=conn, panel=panel)
    sweeps["wave2.h2.near-52w-high"] = run_sweep(specs["wave2.h2.near-52w-high"],
                                                 sweep_grid_h2, conn=conn, panel=panel)
    for sid, sw in sweeps.items():
        jr.register_sweep(sw, strategy_id=sid, version=1)
        log(f"  sweep {sid}: {sw.n_trials} trials, {sw.n_failed} failed")

    log("phase: challenge battery (train_validation results)")
    challenges = {}
    n_trials_map = {"wave2.h1.momentum-6m": 16, "wave2.h2.near-52w-high": 4}
    for sid, res in results.items():
        rep = challenge_finding(res, n_placebo=50,
                                sweep_n_trials=n_trials_map.get(sid),
                                holdout_seal=seal_info, conn=conn)
        challenges[sid] = rep
        jr.register_challenge(rep, strategy_id=sid, version=1)
        log(f"  {sid}: verdict={rep.verdict} pass={rep.n_pass} "
            f"fail={rep.n_fail} inc={rep.n_inconclusive}")

    log("phase: reveal holdout (once) + holdout evaluation")
    train_result_ids = [r.result_id for r in results.values()]
    jr.reveal_holdout("wave2.h1.momentum-6m", 1,
                      runs_evaluated=train_result_ids,
                      note="reveal after preregistered runs + sweeps + challenges")
    holdout_results = {}
    for sid in ("wave2.h1.momentum-6m", "wave2.h2.near-52w-high",
                "wave2.baseline.equal-weight"):
        spec = specs[sid]
        res = run_backtest(spec, conn=conn, panel=panel, phase="holdout")
        holdout_results[sid] = res
        jr.register_run(res)
        rep = challenge_finding(res, n_placebo=50,
                                sweep_n_trials=n_trials_map.get(sid),
                                holdout_seal=seal_info, conn=conn)
        challenges[sid + "@holdout"] = rep
        jr.register_challenge(rep, strategy_id=sid, version=1)
        log(f"  holdout {sid}: status={res.status} verdict={rep.verdict}")
    log("controls are NOT evaluated on the holdout: their rejection is global "
        "by rule and a leaked control on the holdout would only re-teach it")

    log("phase: paired comparisons")
    comparisons = {
        "h1_vs_equal_weight": compare_runs(results["wave2.h1.momentum-6m"],
                                           results["wave2.baseline.equal-weight"]),
        "h2_vs_equal_weight": compare_runs(results["wave2.h2.near-52w-high"],
                                           results["wave2.baseline.equal-weight"]),
        "h1_vs_noise": compare_runs(results["wave2.h1.momentum-6m"],
                                    results["wave2.control.noise.seeded"]),
    }

    log("phase: data coverage + artifacts")
    coverage = {
        "train_validation_window": list_data_coverage(
            conn, "nifty50", WINDOWS[0], WINDOWS[3]),
        "holdout_window": list_data_coverage(conn, "nifty50", WINDOWS[4], WINDOWS[5]),
    }
    _write_artifacts(REPORTS, specs, results, holdout_results, sweeps,
                     challenges, comparisons, coverage, jr)
    log("done")


def _write_artifacts(reports: Path, specs, results, holdout_results, sweeps,
                     challenges, comparisons, coverage, jr) -> None:
    now = datetime.now(timezone.utc).isoformat()

    prereg = {
        "generated_at": now,
        "window_spec": {"train": list(WINDOWS[:2]), "validation": list(WINDOWS[2:4]),
                        "holdout": list(WINDOWS[4:6]),
                        "note": "chronological; embargo structurally enforced by "
                                "label censoring at fold boundaries"},
        "capital_paise": CAPITAL, "slippage_bps": BPS,
        "specs": [
            {"spec_id": s.spec_id, "version": s.version,
             "payload": s.to_payload(), "fingerprint": s.fingerprint(),
             "preregistration_hash": s.preregistration_hash(),
             "declared_negative_control": s.declared_negative_control}
            for s in specs.values()],
    }
    (reports / "wave2_preregistered_specs.json").write_text(
        json.dumps(prereg, indent=1, sort_keys=True), encoding="utf-8")

    # Merge with phase-suffixed keys: train_validation and holdout share spec_ids,
    # so a bare {**results, **holdout_results} would silently drop the 3
    # train_validation payloads via key collision. Suffix per source dict.
    all_results = {}
    for _k, _r in results.items():
        all_results[f"{_k}@{_r.phase}"] = _r
    for _k, _r in holdout_results.items():
        all_results[f"{_k}@{_r.phase}"] = _r
    br = {
        "generated_at": now,
        "note": ("immutable hash-addressed results; result_id = sha256 of the "
                 "canonical payload minus result_id/generated_at and the "
                 "embedded spec's registration instant, so reruns of the same "
                 "preregistered rule set are id-stable; economics vs "
                 "TRI is DATA_BLOCKED on raw unadjusted bars with unverified "
                 "actions; net P&L only where the paper fee schedule covers "
                 "(effective 2026-03-01)"),
        "results": [
            {"spec_id": r.spec["spec_id"], "phase": r.phase, "status": r.status,
             "result_id": r.result_id, "payload": r.to_payload()}
            for r in all_results.values()],
    }
    (reports / "wave2_backtest_results.json").write_text(
        json.dumps(br, indent=1, sort_keys=True), encoding="utf-8")

    with open(reports / "wave2_parameter_sweep.csv", "w", newline="",
              encoding="utf-8") as f:
        wcsv = csv.writer(f)
        wcsv.writerow(["sweep_base_spec", "family", "override", "ok",
                       "n_labeled", "n_abstained", "gross_product",
                       "mean_monthly_gross", "status", "result_id", "error"])
        for sid, sw in sweeps.items():
            fam = sw.base_spec["signal"]["family"]
            for v in sw.variants:
                wcsv.writerow([sid, fam, json.dumps(v["override"], sort_keys=True),
                               v["ok"], v["n_labeled"], v["n_abstained"],
                               v["gross_product"], v["mean_monthly_gross"],
                               v["status"], v["result_id"], v["error"]])

    cr = {
        "generated_at": now,
        "verdict_rules": ("any blocking integrity FAIL -> DATA_BLOCKED; "
                          "economics blocked (raw prices + unverified actions, "
                          "weak membership) -> DATA_BLOCKED; declared negative "
                          "control -> REJECTED; placebo fail -> NO_EDGE; "
                          "otherwise RESEARCH (W2 never promotes)"),
        "challenges": [
            {"run_id": rep.run_id, "phase": _phase_of(rep.run_id, all_results),
             "verdict": rep.verdict, "verdict_reason": rep.verdict_reason,
             "n_pass": rep.n_pass, "n_fail": rep.n_fail,
             "n_inconclusive": rep.n_inconclusive,
             "checks": [dict(c) for c in rep.checks]}
            for rep in challenges.values()],
        "comparisons": comparisons,
        "sweep_plateaus": {sid: sw.to_payload()["plateau"]
                           for sid, sw in sweeps.items()},
    }
    (reports / "wave2_challenge_report.json").write_text(
        json.dumps(cr, indent=1, sort_keys=True, default=str), encoding="utf-8")

    statuses = {}
    for sid, spec in specs.items():
        st = jr.status(sid, spec.version)
        statuses[sid] = st
    hr = {
        "generated_at": now,
        "discipline": ("holdout sealed before any run; single reveal after "
                       "tuning; an unsealed holdout can never be reused fresh"),
        "journal_path": str(jr.path),
        "chain_intact_all": all(s["chain_intact"] for s in statuses.values()),
        "statuses": statuses,
    }
    (reports / "wave2_holdout_registry.json").write_text(
        json.dumps(hr, indent=1, sort_keys=True), encoding="utf-8")

    (reports / "wave2_data_coverage.json").write_text(
        json.dumps(coverage, indent=1, sort_keys=True, default=str),
        encoding="utf-8")

    manifest = {
        "generated_at": now,
        "artifacts": {},
        "result_ids": {r.spec["spec_id"] + "@" + r.phase: r.result_id
                       for r in all_results.values()},
        "verdicts": {k: v.verdict for k, v in challenges.items()},
    }
    for name in ("wave2_research_journal.jsonl", "wave2_preregistered_specs.json",
                 "wave2_backtest_results.json", "wave2_parameter_sweep.csv",
                 "wave2_challenge_report.json", "wave2_holdout_registry.json",
                 "wave2_data_coverage.json"):
        p = reports / name
        manifest["artifacts"][name] = hashlib.sha256(
            p.read_bytes()).hexdigest() if p.exists() else None
    (reports / "wave2_artifacts_manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    log(f"artifacts written to {reports}")


def _phase_of(run_id: str, all_results: dict) -> str:
    for r in all_results.values():
        if r.result_id == run_id:
            return r.phase
    return "unknown"


if __name__ == "__main__":
    main()
