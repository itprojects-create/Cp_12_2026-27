"""Hermetic tests for the post-W6 academic accuracy diagnostic."""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from quantplus_intelligence.research_v3 import warehouse as W
from quantplus_intelligence.research_v3.college_accuracy.contracts import (
    EVIDENCE_TIER, SPEC_SCHEMA, compute_spec_hash, semantic_hash,
    verify_sealed_spec, write_sealed_spec)
from quantplus_intelligence.research_v3.college_accuracy.metrics import (
    clustered_accuracy_interval, confidence_coverage_curve,
    paired_accuracy_difference_interval, summarize_directional)
from quantplus_intelligence.research_v3.college_accuracy.runner import (
    _attempt, _decision_ts, build_open_label_fast, training_majority,
    weekly_sessions)
from quantplus_intelligence.research_v3.quantlab import FeaturePanel, build_label
from quantplus_intelligence.research_v3.quantlab.folds import make_folds, set_session_index
from quantplus_intelligence.research_v3.quantlab.models import _standardizer

IST = timezone(timedelta(hours=5, minutes=30))


def _sessions(n=340):
    out, day = [], date(2020, 1, 6)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


SESSIONS = _sessions()


def _fixture(path, *, flat=False, discontinuity=False, missing_exit=False):
    conn = W.connect(path)
    for symbol, drift in (("AAA", 0.001), ("BBB", -0.0005)):
        prior = 10_000 if symbol == "AAA" else 20_000
        for index, session in enumerate(SESSIONS):
            open_paise = prior
            close = prior if flat else round(prior * (1 + drift))
            if discontinuity and symbol == "AAA" and index == 300:
                open_paise = round(prior * 0.5)
                close = round(close * 0.5)
            available = (datetime.fromisoformat(session).replace(tzinfo=IST)
                         + timedelta(days=1, minutes=15)).isoformat()
            conn.execute(
                "INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (session, symbol, "EQ", "ISIN" + symbol, open_paise,
                 max(open_paise, close), min(open_paise, close), close, prior,
                 1000, 1_000_000, 10, "fixture", "2026-01-01", available,
                 "fixture raw", "FIXTURE"))
            prior = close
        conn.execute(
            "INSERT INTO membership_spells VALUES (?,?,?,?,?,?,?,?,?)",
            ("999", "nifty50", symbol, SESSIONS[0], None, "press_release",
             1, "fixture", "fixture"))
    for session in SESSIONS:
        conn.execute("INSERT INTO benchmark_bars VALUES "
                     "('NIFTY50_TRI',?,1000.0,'fixture','2026-01-01','fixture')",
                     (session,))
    if missing_exit:
        conn.execute("DELETE FROM daily_bars WHERE symbol='AAA' AND session=?",
                     (SESSIONS[306],))
    conn.commit()
    return conn, FeaturePanel(conn, "nifty50")


def _spec_payload():
    payload = {
        "schema": SPEC_SCHEMA,
        "spec_version": "test",
        "evidence_tier": EVIDENCE_TIER,
        "holdout_policy": {"revealed_w2_holdout": ["2024-06-21", "2026-09-17"],
                           "fresh_sealed_holdout": "NEW_SEALED_HOLDOUT_UNAVAILABLE"},
    }
    payload["spec_payload_sha256"] = compute_spec_hash(payload)
    return payload


def _row(session, true_class, pred, *, state="ADMISSIBLE", tie=False,
         symbol="AAA", fold="wf1"):
    return {"session": session, "symbol": symbol, "fold_id": fold,
            "label_state": state, "true_class": true_class, "tie": tie,
            "predicted_class": pred}


def test_spec_hash_and_immutable_write(tmp_path):
    payload = _spec_payload()
    assert verify_sealed_spec(payload) == (True, "sealed spec valid")
    path = tmp_path / "spec.json"
    sealed = write_sealed_spec(path, {k: v for k, v in payload.items()
                                      if k not in ("schema", "spec_payload_sha256")})
    assert sealed["spec_payload_sha256"] == compute_spec_hash(sealed)
    with pytest.raises(RuntimeError, match="refusing to replace"):
        write_sealed_spec(path, {"different": True})


def test_spec_tamper_and_holdout_policy_refused():
    payload = _spec_payload()
    payload["spec_version"] = "tampered"
    assert verify_sealed_spec(payload)[0] is False
    payload = _spec_payload()
    payload["holdout_policy"]["fresh_sealed_holdout"] = "REUSED"
    payload["spec_payload_sha256"] = compute_spec_hash(payload)
    assert verify_sealed_spec(payload)[0] is False


def test_open_to_open_session_indexing_and_no_same_close_fill(tmp_path):
    _conn, panel = _fixture(tmp_path / "db.sqlite3")
    decision_session = SESSIONS[280]
    label = build_label(panel, "AAA", _decision_ts(decision_session), 5,
                        exit_ref="OPEN")
    decision_ix = SESSIONS.index(decision_session)
    assert label.decision_session == decision_session
    assert label.entry_session == SESSIONS[decision_ix + 1]
    assert label.exit_session == SESSIONS[decision_ix + 6]
    assert label.entry_session > decision_session


def test_fast_batch_label_matches_authoritative_w1_open_label(tmp_path):
    _conn, panel = _fixture(tmp_path / "parity.sqlite3")
    for horizon in (5, 20):
        for session in (SESSIONS[260], SESSIONS[280], SESSIONS[300]):
            authoritative = build_label(panel, "AAA", _decision_ts(session), horizon,
                                        exit_ref="OPEN")
            fast = build_open_label_fast(panel, "AAA", _decision_ts(session), horizon)
            assert fast.status == authoritative.status
            assert fast.admissibility == authoritative.admissibility
            assert fast.entry_session == authoritative.entry_session
            assert fast.exit_session == authoritative.exit_session
            assert fast.exit_extended == authoritative.exit_extended
            assert fast.gross_return == pytest.approx(authoritative.gross_return)


def test_strict_sign_and_zero_tie_definition(tmp_path):
    _conn, panel = _fixture(tmp_path / "flat.sqlite3", flat=True)
    label = build_label(panel, "AAA", _decision_ts(SESSIONS[280]), 5,
                        exit_ref="OPEN")
    attempt = _attempt(label, fold_id="wf1", symbol="AAA",
                       session=SESSIONS[280], horizon=5)
    assert attempt["gross_open_to_open_return"] == 0.0
    assert attempt["tie"] is True and attempt["true_class"] is None


def test_pit_cutoff_excludes_future_bar(tmp_path):
    _conn, panel = _fixture(tmp_path / "pit.sqlite3")
    session = SESSIONS[280]
    snapshot = panel.snapshot("AAA", _decision_ts(session))
    assert snapshot.decision_session == session
    later = panel.snapshot("AAA", _decision_ts(SESSIONS[281]))
    assert later.decision_session == SESSIONS[281]
    assert later.features["ret_5"] != snapshot.features["ret_5"]


def test_action_window_quarantine_and_discontinuity_detection(tmp_path):
    _conn, panel = _fixture(tmp_path / "action.sqlite3", discontinuity=True)
    label = build_label(panel, "AAA", _decision_ts(SESSIONS[290]), 20,
                        exit_ref="OPEN")
    assert label.admissibility == "DATA_BLOCKED_ACTION_WINDOW"
    assert label.contamination
    detected = panel.holding_discontinuities("AAA", SESSIONS[295], SESSIONS[305])
    assert detected
    fast = build_open_label_fast(panel, "AAA", _decision_ts(SESSIONS[290]), 20)
    assert fast.admissibility == label.admissibility
    assert fast.contamination


def test_missing_exit_bar_extends_and_is_disclosed(tmp_path):
    _conn, panel = _fixture(tmp_path / "missing.sqlite3", missing_exit=True)
    # Entry at 301 and target h5 exit at 306, whose AAA bar was deleted.
    label = build_label(panel, "AAA", _decision_ts(SESSIONS[300]), 5,
                        exit_ref="OPEN")
    assert label.status == "OK" and label.exit_extended is True
    assert label.exit_session > SESSIONS[306]
    fast = build_open_label_fast(panel, "AAA", _decision_ts(SESSIONS[300]), 5)
    assert fast.exit_extended and fast.exit_session == label.exit_session
    assert fast.gross_return == pytest.approx(label.gross_return)


def test_holdout_overlap_refusal_and_twenty_session_embargo(tmp_path):
    _conn, panel = _fixture(tmp_path / "fold.sqlite3")
    set_session_index(panel.sessions)
    folds = make_folds(panel.sessions, SESSIONS[0], SESSIONS[200], SESSIONS[-1],
                       4, embargo_sessions=20)
    assert all(fold.embargo_sessions == 20 for fold in folds)
    with pytest.raises(ValueError, match="quarantined"):
        make_folds(panel.sessions + ["2025-01-01"], "2023-01-01", "2024-07-01",
                   "2025-01-01", 2, embargo_sessions=20)


def test_training_only_standardizer_has_no_validation_argument():
    import numpy as np
    train = np.array([[0.0, 10.0], [2.0, 14.0]])
    mu, sd = _standardizer(train)
    assert mu.tolist() == [1.0, 12.0]
    assert sd.tolist() == [1.0, 2.0]


def test_confusion_matrix_denominators_and_constant_up_baseline():
    rows = [_row("d1", 1, 1, symbol="a"), _row("d1", 0, 1, symbol="b"),
            _row("d2", 1, 1, symbol="c"), _row("d2", None, 1, tie=True, symbol="d"),
            _row("d2", None, 1, state="NO_LABEL", symbol="e")]
    result = summarize_directional(rows)
    assert result["confusion_matrix"] == {"tn": 0, "fp": 1, "fn": 0, "tp": 2}
    assert result["n_eligible_non_tie"] == 3 and result["n_ties"] == 1
    assert result["answered_accuracy"] == pytest.approx(2 / 3)


def test_majority_baseline_uses_training_rows_only():
    prevalence, predicted = training_majority(
        [{"y": 0.1}, {"y": 0.2}, {"y": -0.1}])
    assert prevalence == pytest.approx(2 / 3) and predicted == 1
    prevalence2, predicted2 = training_majority(
        [{"y": -0.1}, {"y": -0.2}, {"y": 0.1}])
    assert prevalence2 == pytest.approx(1 / 3) and predicted2 == 0


def test_abstention_coverage_and_unconditional_accuracy():
    rows = [_row("d1", 1, 1, symbol="a"), _row("d1", 0, None, symbol="b"),
            _row("d2", 0, 0, symbol="c"), _row("d2", 1, None, symbol="d")]
    result = summarize_directional(rows)
    assert result["coverage"] == 0.5 and result["n_abstentions"] == 2
    assert result["answered_accuracy"] == 1.0
    assert result["unconditional_accuracy"] == 0.5


def test_clustered_interval_groups_dates_and_is_deterministic():
    rows = [_row(f"d{day}", value % 2, value % 2, symbol=f"s{value}")
            for day in range(8) for value in range(10)]
    first = clustered_accuracy_interval(rows, block_sessions=4,
                                        n_bootstrap=200, seed=7)
    second = clustered_accuracy_interval(rows, block_sessions=4,
                                         n_bootstrap=200, seed=7)
    assert first == second
    assert first["decision_sessions"] == 8
    assert first["effective_nonoverlap_periods"] == 2
    assert first["lower_95"] == 1.0 == first["upper_95"]


def test_paired_difference_uses_identical_keys():
    model = [_row("d1", 1, 1, symbol="a"), _row("d2", 0, 0, symbol="b")]
    base = [_row("d1", 1, 0, symbol="a"), _row("d2", 0, 0, symbol="b")]
    result = paired_accuracy_difference_interval(
        model, base, block_sessions=1, n_bootstrap=100, seed=3)
    assert result["paired_n"] == 2 and result["difference"] == 0.5


def test_fixed_confidence_grid_retains_every_point():
    rows = [dict(_row("d1", 1, 1, symbol="a"), score=0.9),
            dict(_row("d1", 0, 0, symbol="b"), score=0.4),
            dict(_row("d2", 1, 1, symbol="c"), score=0.54)]
    curve = confidence_coverage_curve(rows, [0.50, 0.55, 0.60, 0.65])
    assert [row["probability_threshold"] for row in curve] == [0.5, 0.55, 0.6, 0.65]
    assert curve[0]["coverage"] == 1.0
    assert curve[-1]["coverage"] < 1.0


def test_weekly_cadence_and_semantic_result_ids_are_stable():
    weeks = weekly_sessions(SESSIONS, SESSIONS[0], SESSIONS[-1])
    assert weeks == sorted(set(weeks))
    payload = {"model": "logistic", "horizon": 20, "fold": "wf1"}
    assert semantic_hash(payload) == semantic_hash(dict(payload))
    assert semantic_hash({**payload, "horizon": 5}) != semantic_hash(payload)


def test_protected_store_hashes_do_not_change_on_import_and_metrics():
    root = Path(__file__).resolve().parents[2]
    candidates = [
        root / "reports/alpha_v3_1/wave6_signal_and_paper_ledger.jsonl",
        root / "reports/alpha_v3_1/backups/forecast_ledger_w0_backup.sqlite3",
    ]
    existing = [path for path in candidates if path.is_file()]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in existing}
    summarize_directional([_row("d1", 1, 1)])
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in existing}
    assert before == after


def test_no_network_provider_or_order_authority_surface():
    package = Path(__file__).resolve().parents[1] / "quantplus_intelligence/research_v3/college_accuracy"
    script = Path(__file__).resolve().parents[1] / "scripts/college_accuracy_run.py"
    verifier = Path(__file__).resolve().parents[1] / "scripts/college_accuracy_verify.py"
    sources = list(package.glob("*.py")) + [script, verifier]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "requests." not in text and "urllib.request" not in text
        tree = ast.parse(text)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(name.startswith("app") for name in imported)
        assert "place_order" not in text and "broker_order" not in text
