"""Forward-week ritual tests: hermetic (temp DB via conftest, zero network).

All network-touching inputs are injected (forward_bars=[], fingerprint
override); the ritual must then record infancy honestly: 0 forward decisions,
IR 0.0, clean verdicts, equal allocation, forbidden-kind rejection at parse,
and the allowlisted candidate failing promotion ON RECORD with
"test slice too small" (no forward entries settled yet).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.db import sqlite_conn
from app.evo import store

NOW = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
G = {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
     "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False}
IDS = [f"TEST-FW{i}" for i in range(3)]


@pytest.fixture()
def founders():
    store.init()
    for i in IDS:
        try:
            store.birth(i, i.lower(), dict(G))
        except ValueError:
            pass  # idempotent re-run
    yield
    db = sqlite_conn()
    for i in IDS:
        db.execute("DELETE FROM evo_windows WHERE variant_id=?", (i,))
        db.execute("DELETE FROM evo_variants WHERE id=?", (i,))
    db.execute("DELETE FROM foundry_log WHERE rationale LIKE 'TEST-FW%'")
    db.commit()


def _cand():
    return {"kind": "veto_band_edge",
            "params": {"band_lo": 0.5, "band_hi": 0.75, "veto": 1.0,
                       "regime": "STRESSED", "breadth": "low"},
            "rationale": "TEST-FW candidate falsifier statement"}


def test_week_records_infancy_not_evidence(founders, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    from forward_week import run_week
    out = str(tmp_path / "w.json")
    art = run_week(now=NOW, forward_bars=[], fingerprint_override="CALM|UP|mid",
                   candidate=_cand(), out_path=out)
    assert art["window_no"] == 1
    assert art["n_decisions_this_window"] == 0
    assert art["scope"].startswith("forward-only")
    assert len(art["judged"]) == 3
    for j in art["judged"]:
        assert j["n_decisions"] == 0 and j["ir"] == 0.0
        assert j["transition"] == "clean" and "infancy" in " ".join(j["reasons"])
    # equal-weight infancy allocation, sums to 1
    assert abs(sum(art["allocation"].values()) - 1.0) < 1e-9
    assert set(art["allocation"]) == set(IDS)
    # forbidden kind rejected at parse, never evaluated
    assert art["foundry"]["forbidden_probe"]["rejected"] is True
    # allowlisted candidate validated on forward rows only -> too small, logged
    cand = art["foundry"]["candidate"]
    assert cand["promoted"] is False and cand["reason"] == "test slice too small"
    row = sqlite_conn().execute(
        "SELECT promoted FROM foundry_log WHERE rationale='TEST-FW candidate falsifier statement'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None and row[0] == 0
    # artifact persisted as-is
    assert json.loads(open(out, encoding="utf-8").read())["window_no"] == 1


def test_genome_shaped_kind_routes_to_evo_queue(founders, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    from forward_week import run_week
    art = run_week(now=NOW, forward_bars=[], fingerprint_override="CALM|UP|mid",
                   candidate={"kind": "topK_value", "params": {"K": 30},
                              "rationale": "TEST-FW genome route"},
                   out_path=str(tmp_path / "w2.json"))
    # empty forward rows: gate holds for every kind before policy dispatch
    assert art["foundry"]["candidate"]["promoted"] is False
    assert art["foundry"]["candidate"]["reason"] == "test slice too small"
    # routing mechanism itself: genome-shaped kinds have no veto-table
    # semantics and must raise (evo-queue route, never live-direct)
    from app.foundry import proposals as P
    from app.foundry import validate as V
    prop = P.parse("topK_value", {"K": 30}, rationale="TEST-FW route check")
    with pytest.raises(ValueError):
        V.candidate_policy(prop, lambda row: 0.0)


def test_dry_run_writes_nothing(founders, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    from forward_week import run_week
    out = str(tmp_path / "dry.json")
    art = run_week(now=NOW, dry_run=True, forward_bars=[],
                   fingerprint_override="CALM|UP|mid",
                   candidate=_cand(), out_path=out)
    assert art["dry_run"] is True and art["allocation"] == {}
    assert all(store.window_count(i) == 0 for i in IDS)
    import os
    assert not os.path.exists(out)
