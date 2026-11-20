"""Evaluation-expansion tests (Phase 5). All synthetic — nothing tuned on history."""
from __future__ import annotations

import pytest

from app.eval import benchmarks as BM
from app.eval import concentration as CONC
from app.eval import data_quality as DQ
from app.eval import incremental_alpha as IA
from app.eval import loo as LOO
from app.eval import placebo as PLA
from app.eval import regimes as REG
from app.eval import report as REP
from app.eval import stability as STAB
from app.eval import stats as S


def _series(base=0.001, n=60, bump=0.0):
    return [base + (bump if i % 10 == 0 else 0.0) + (0.0005 if i % 2 else -0.0005)
            for i in range(n)]


def test_stats_helpers():
    assert S.sharpe([0.01] * 60) == 0.0  # zero variance -> 0, never inf
    assert S.sharpe([]) == 0.0
    mdd, dur = S.max_drawdown([1.0, 1.1, 0.9, 1.2])
    assert round(mdd, 4) == round(1 - 0.9 / 1.1, 4) and dur == 1
    assert S.cvar([0.05, -0.10, -0.02, 0.01]) < 0
    r = S.ols_alpha_beta([0.02] * 10, [0.01] * 10)
    assert r["low_confidence"] is True and r["n"] == 10  # weak sample flagged
    r2 = S.ols_alpha_beta([2 * x for x in range(40)], list(range(40)))
    assert abs(r2["beta"] - 2.0) < 1e-9 and r2["low_confidence"] is False


def test_incremental_alpha_beta_explained():
    bench = [0.01] * 60
    cand = [0.012] * 60  # beta ~1.2 on flat series? flat->beta 0; use sloped
    bench = [0.001 * (i % 5) for i in range(60)]
    cand = [1.5 * b + 0.0002 for b in bench]
    rep = IA.evaluate(cand, list(bench), list(bench))
    assert abs(rep["candidate_beta"] - 1.5) < 0.05
    assert rep["estimated_alpha"] > 0 and rep["n"] == 60
    assert "alpha_ci95" in rep
    assert IA.evaluate([0.01], [0.01], [0.01])["insufficient_data"] is True


def test_concentration_flags_lucky_stock():
    contrib = [{"id": f"S{i}", "pnl": 10.0, "sector": "X", "year": "2023"} for i in range(9)]
    contrib.append({"id": "LUCKY", "pnl": 910.0, "sector": "Y", "year": "2023"})
    rep = CONC.analyze(contrib)
    assert rep["top_1_share"] == pytest.approx(0.91, abs=0.01)
    assert rep["single_name_dependent"] is True
    assert rep["without_best"] == pytest.approx(90.0)
    assert rep["without_top_year"]["remaining"] == pytest.approx(0.0)
    flat = [{"id": f"S{i}", "pnl": 10.0} for i in range(10)]
    assert CONC.analyze(flat)["single_name_dependent"] is False


def test_loo_wrappers():
    items = [{"id": "A", "pnl": 100.0, "sector": "X", "year": "2023", "regime": "UP"},
             {"id": "B", "pnl": 50.0, "sector": "Y", "year": "2024", "regime": "DOWN"},
             {"id": "C", "pnl": -10.0, "sector": "X", "year": "2024", "regime": "UP"}]
    assert LOO.leave_one_stock_out(items)["worst_drop"] == "A"
    assert LOO.leave_one_sector_out(items)["baseline"] == pytest.approx(140.0)
    assert LOO.leave_one_year_out(items)["n_groups"] == 2
    assert LOO.leave_one_regime_out(items)["n_groups"] == 2
    top = LOO.leave_top_contributor_out(items)
    assert top["top"] == "A" and top["remaining"] == pytest.approx(40.0)


def test_regimes_grouping_and_dependence():
    daily = [0.01] * 20 + [0.005] * 20
    labels = {i: ("UP_TREND" if i < 20 else "DOWN_TREND") for i in range(40)}
    rep = REG.analyze(daily, labels)
    assert rep["n_regimes_present"] == 2 and rep["unlabeled_bars"] == 0
    dep = REG.regime_dependence(rep)
    assert dep["best_regime"] == "UP_TREND"
    assert dep["best_share"] == pytest.approx(0.2 / 0.3, abs=1e-3)
    assert REG.analyze([0.01], {})["single_regime"] is False


def test_stability_spots_isolated_peak():
    grid = [40, 45, 50, 55, 60]
    assert STAB.analyze(grid, {g: 0.1 for g in grid})["isolated_peak"] is False
    assert STAB.analyze(grid, {40: -0.1, 45: -0.05, 50: 0.9, 55: -0.02, 60: 0.0})[
        "isolated_peak"] is True
    with pytest.raises(ValueError):
        STAB.analyze(grid, {40: 0.1})


def test_placebo_math():
    assert PLA.permutation_pvalue(0.9, [0.1] * 50)["p_value"] < 0.05
    assert PLA.permutation_pvalue(0.05, [0.1] * 50)["p_value"] > 0.10
    assert PLA.permutation_pvalue(0.5, [])["n_null"] == 0
    shuffles = PLA.shuffled_labels([1.0, 2.0, 3.0], seed=1, n=5)
    assert len(shuffles) == 5 and sorted(shuffles[0]) == [1.0, 2.0, 3.0]
    assert PLA.shuffled_labels([1.0], seed=1, n=2) == [[1.0], [1.0]]
    rr = PLA.random_ranking_metric(10.0, 5, 20, lambda order: float(sum(order)))
    assert rr["n_null"] == 20


def test_benchmark_attribution():
    bench = [0.001 * (i % 7) + (0.0002 if i % 3 else -0.0002) for i in range(60)]
    cand = [b + 0.0005 + (0.0001 if i % 2 else -0.0001) for i, b in enumerate(bench)]
    a = BM.attribute(cand, bench)
    assert a["active_return"] > 0 and abs(a["beta"] - 1.0) < 0.05
    assert a["information_ratio"] > 0
    multi = BM.compare_many(cand, {"bench": bench, "cash": [0.0] * 60})
    assert set(multi) == {"bench", "cash"}
    assert BM.attribute([0.01], [0.01])["insufficient_data"] is True


def test_data_quality_gates():
    assert DQ.assess()["verdict"] == "PASS"
    assert DQ.assess(missingness=0.6)["verdict"] in ("FLAG", "REJECT")
    assert DQ.assess(pit_confidence=0.2)["verdict"] == "REJECT"
    with pytest.raises(ValueError):
        DQ.assess(coverage=2.0)


def test_failure_first_report_order():
    contrib = [{"id": "LUCKY", "pnl": 1000.0}, {"id": "B", "pnl": 10.0}]
    rep = REP.summarize_candidate(_series(), _series(), _series(),
                                  contributions=contrib)
    assert rep["verdict"] == "REJECT"
    assert any("single-name" in w for w in rep["why_fake"])
    assert "concentration" in rep["blocks"] and "missing_evidence" in rep
    thin = REP.summarize_candidate([0.01], [0.01], [0.01])
    assert thin["verdict"] == "REJECT"  # insufficient history fails closed
    assert "stability" in thin["missing_evidence"] and "placebo" in thin["missing_evidence"]
