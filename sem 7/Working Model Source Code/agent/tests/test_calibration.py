"""Calibration infrastructure tests (P6, §78 calibration block). Hermetic."""
from __future__ import annotations

from app.db import sqlite_conn
from app.research import calibration as CAL


def _clean():
    CAL.init_tables()
    sqlite_conn().execute("DELETE FROM research_predictions WHERE hypothesis_fp LIKE 'TEST-%'")
    sqlite_conn().execute("DELETE FROM research_outcomes WHERE hypothesis_fp LIKE 'TEST-%'")
    sqlite_conn().commit()


def _hypo(p=0.8):
    return {"estimated_probability_survives_backtest": p,
            "estimated_probability_survives_falsification": p,
            "estimated_probability_reaches_shadow": 0.3,
            "estimated_probability_reaches_promotion": 0.1}


def test_first_write_wins_no_hindsight_edits():
    _clean()
    r1 = CAL.record_prediction("TEST-CAL-1", "factor", _hypo(0.8))
    r2 = CAL.record_prediction("TEST-CAL-1", "factor", _hypo(0.1))
    assert r1["priors"]["backtest"] == 0.8 and r2["priors"]["backtest"] == 0.8
    CAL.settle_prediction("TEST-CAL-1", "FAILED_BACKTEST")
    CAL.settle_prediction("TEST-CAL-1", "PROMOTED")  # progression allowed, timestamped
    _clean()


def test_insufficient_sample_safe():
    _clean()
    for i in range(3):
        CAL.record_prediction(f"TEST-CAL-S{i}", "factor", _hypo())
        CAL.settle_prediction(f"TEST-CAL-S{i}", "PROMOTED")
    rep = CAL.calibration_report()
    assert rep["status"] == "INSUFFICIENT_CALIBRATION_SAMPLE" and rep["n"] == 3
    _clean()


def test_brier_and_bins_with_adequate_sample():
    _clean()
    for i in range(30):  # perfect predictors: p=1 -> PROMOTED, p=0 fails
        fp = f"TEST-CAL-B{i}"
        CAL.record_prediction(fp, "falsifier" if i % 2 else "factor",
                              _hypo(1.0) if i % 3 else _hypo(0.0))
        CAL.settle_prediction(fp, "PROMOTED" if i % 3 else "FAILED_BACKTEST")
    rep = CAL.calibration_report(min_n=30)
    assert rep["status"] == "REPORTED" and rep["n"] == 30
    assert rep["stages"]["backtest"]["brier"] == 0.0  # perfect
    assert len(rep["stages"]["shadow"]["bins"]) == 5
    roles = CAL.role_value_metrics()["by_role"]
    assert roles["factor"]["resolved"] + roles["falsifier"]["resolved"] == 30
    assert roles["factor"]["proposed"] >= 1
    _clean()


def test_capital_path_cannot_read_calibration():
    import pathlib
    for pkg in ("app/core", "app/evo", "app/agents"):
        for p in pathlib.Path(pkg).glob("*.py"):
            src = p.read_text(encoding="utf-8")
            assert "research.calibration" not in src and "research_calibration" not in src, p.name
            assert "estimated_probability_" not in src, p.name
    from app import schemas as S
    assert "estimated_probability" not in S.FinalDecision.model_json_schema().__str__()


def test_comparison_frame_binds_inputs():
    a = CAL.comparison_frame("c", "m", "u", 100, 5, "g")
    b = CAL.comparison_frame("c", "m", "u", 100, 5, "g")
    c = CAL.comparison_frame("c", "m", "u", 101, 5, "g")
    assert a["frame_hash"] == b["frame_hash"] != c["frame_hash"]
