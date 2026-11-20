"""P5 trial-ledger + DSR-report tests (§78 DSR block). Hermetic temp DB."""
from __future__ import annotations

from app.db import sqlite_conn
from app.eval import dsr as DSR
from app.eval import trials as TR


def _clean():
    TR.init_tables()
    sqlite_conn().execute("DELETE FROM eval_trials WHERE trial_id LIKE 'TEST-%'")
    sqlite_conn().commit()


def test_ledger_is_append_only_and_monotonic():
    _clean()
    assert not any(n.startswith(("update", "delete", "remove", "purge"))
                   for n in dir(TR) if not n.startswith("_"))
    before = TR.trial_count()
    assert TR.record_trial("TEST-T1", "return", 0.7)["duplicate"] is False
    assert TR.record_trial("TEST-T1", "return", 0.9)["duplicate"] is True  # no double count
    assert TR.record_trial("TEST-T2", "research", None)["sharpe"] is None
    assert TR.trial_count() == before + 2  # dead-or-alive: count never decreases
    assert TR.return_sharpes().count(0.7) == 1  # original kept, not overwritten
    import pytest
    with pytest.raises(ValueError):
        TR.record_trial("TEST-X", "vibes", 1.0)
    _clean()


def test_seed_covers_documented_history():
    _clean()
    seed = TR.seed_historical()
    assert TR.trial_count("return") >= len(DSR.TRIALS)  # never undercounted
    assert TR.trial_count("research") >= 6
    again = TR.seed_historical()
    assert again["added"] == 0 and again["total"] == seed["total"]  # idempotent
    ids = {t["trial_id"] for t in TR.list_trials()}
    assert "hist-retry-m10" in ids and "hist-ablation-overlay" in ids
    _clean()


def test_dsr_report_carries_registry_fields():
    _clean()
    TR.seed_historical()
    rep = TR.dsr_report("v4-broad", "strat-x", "2021-01-01..2026-10-01",
                        1.509, 1420, -0.45, 10.3)
    for k in ("strategy_id", "strategy_fingerprint", "tested_period",
              "number_of_trials", "selection_history", "observed_sharpe",
              "expected_max_sharpe", "deflated_sharpe", "p_value",
              "registry_version"):
        assert k in rep, k
    assert rep["registry_version"] == "DSR_REGISTRY_V1"
    assert rep["number_of_trials"] >= len(DSR.TRIALS)
    assert 0.0 <= rep["deflated_sharpe"] <= 1.0
    assert rep["p_value"] == round(1 - rep["deflated_sharpe"], 4)
    _clean()
