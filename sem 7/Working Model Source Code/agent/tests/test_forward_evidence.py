"""P7 forward-evidence tests (§87 settlement + counts + backtest refusal). Hermetic."""
from __future__ import annotations

import pytest

from app.db import sqlite_conn
from app.evo import arena as ARENA
from app.forward import records as REC
from app.forward import settle as SET


def _clean():
    REC.init_tables()
    sqlite_conn().execute("DELETE FROM forward_decisions WHERE decision_id LIKE 'FWD-%'")
    sqlite_conn().commit()


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def test_outcome_unsettled_until_maturity():
    REC.record_decision("2026-10-01T00:00:00+00:00", "INFY.NS", "v4", "strat-x",
                        0.05, 0.05, snapshot_id="SNAP-1")
    assert len(REC.unsettled()) == 1 and REC.matured_evidence() == []  # §48/§50
    out = SET.settle_as_of("2026-10-03T00:00:00+00:00", horizon_days=5,
                           price_fn=lambda i, s, e: (100.0, 110.0))
    assert out == {"settled": 0, "pending": 1, "failed": 0,
                   "as_of": "2026-10-03T00:00:00+00:00"}  # immature: no label
    out = SET.settle_as_of("2026-10-10T00:00:00+00:00", horizon_days=5,
                           price_fn=lambda i, s, e: (100.0, 110.0))
    assert out["settled"] == 1
    assert REC.matured_evidence()[0]["outcome"].startswith("GAIN")
    again = SET.settle_as_of("2026-11-01T00:00:00+00:00", horizon_days=5,
                             price_fn=lambda i, s, e: (100.0, 1.0))
    assert again["settled"] == 0  # exactly-once: rerun changes nothing


def test_unavailable_prices_stay_unsettled_and_idempotent_decisions():
    r1 = REC.record_decision("2026-10-01T00:00:00+00:00", "X.NS", "v4", "s",
                             0.05, 0.05)
    r2 = REC.record_decision("2026-10-01T00:00:00+00:00", "X.NS", "v4", "s",
                             0.05, 0.05)
    assert r1["decision_id"] == r2["decision_id"]  # content-idempotent
    out = SET.settle_as_of("2026-10-10T00:00:00+00:00",
                           price_fn=lambda i, s, e: None)
    assert out["pending"] == 1 and out["settled"] == 0  # never estimated


def test_no_first_seen_mutation_api():
    import app.forward.settle as S
    import app.forward.records as R
    for mod in (S, R):
        assert not any(n.startswith(("update_first", "rewrite_first", "backdate",
                                     "delete", "purge"))
                       for n in dir(mod) if not n.startswith("_"))


def test_arena_refuses_backtest_judgment():
    from app.evo import store as ST
    ST.init()
    ST.birth("TEST-FWD-J", "j", {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
                                 "gross_cap": 1.0, "turnover_delta": 0.015,
                                 "veto_off": False})
    try:
        with pytest.raises(ValueError):
            ARENA.judge_round("TEST-FWD-J", 1, 60, 0.5, 0, 10**9, source="backtest")
        r = ARENA.judge_round("TEST-FWD-J", 1, 5, 0.5, 0, 10**9)  # forward default
        assert r["transition"] == "clean"
    finally:
        db = sqlite_conn()
        db.execute("DELETE FROM evo_windows WHERE variant_id='TEST-FWD-J'")
        db.execute("DELETE FROM evo_variants WHERE id='TEST-FWD-J'")
        db.commit()


def test_experiment_counts_shape():
    counts = SET.experiment_counts("2026-10-10T00:00:00+00:00", "2026-10-10T23:59:59+00:00")
    for k in ("announcements_received", "pit_eligible_announcements", "classified_events",
              "abstentions", "blocked_entries", "independent_companies",
              "independent_event_days"):
        assert k in counts
