"""Death-engine MVP tests: synthetic ledgers only, zero tokens, zero network (prereg_evo_founders.md §6)."""
import os

import pytest

from app.evo import store
from app.evo.genome import FOUNDERS, Genome, breadth_bucket, fingerprint, mutate


@pytest.fixture(autouse=True)
def _clean():
    store.init()
    yield
    from app.db import sqlite_conn
    db = sqlite_conn()
    for t in ("evo_variants", "evo_windows", "evo_tombstones", "evo_lineage"):
        db.execute(f"DELETE FROM {t} WHERE {'variant_id' if t != 'evo_variants' and t != 'evo_lineage' else ('child_id' if t == 'evo_lineage' else 'id')} LIKE 'TEST-%'")
    db.commit()


def test_founders_valid_and_eight():
    assert len(FOUNDERS) == 8
    for _, g in FOUNDERS:
        g.validate()


def test_genome_rejects_out_of_range():
    with pytest.raises(ValueError):
        Genome(topK=42).validate()
    with pytest.raises(ValueError):
        Genome(veto_strictness=3.0).validate()


def test_mutate_single_gene_bounded():
    kids = mutate(Genome(50, 1.0, "on", 1.0, 0.015), max_children=2)
    assert 1 <= len(kids) <= 2
    for k in kids:
        k.validate()
        assert len(Genome(50, 1.0, "on", 1.0, 0.015).diff_genes(k)) == 1
        assert k.veto_off is False


def test_fingerprint_buckets():
    assert fingerprint("CALM", "UP", 0.2) == "CALM|UP|low"
    assert fingerprint("CALM", "UP", 0.5) == "CALM|UP|mid"
    assert fingerprint("CALM", "UP", 0.8) == "CALM|UP|high"
    assert breadth_bucket(0.40) == "mid"  # boundary documented


def test_infancy_not_judgeable():
    from app.evo import arena
    store.birth("TEST-A", "a", {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
                                "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False})
    r = arena.judge_round("TEST-A", 1, 30, -5.0, 10**9, 10**6)
    assert r["transition"] == "clean" and r["status"] == "ALIVE"


def test_two_strikes_kill_and_bury():
    from app.evo import arena
    store.birth("TEST-B", "b", {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
                                "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False})
    r1 = arena.judge_round("TEST-B", 1, 60, -0.4, 0, 10**9, death_fingerprint="CALM|UP|mid")
    assert r1["transition"] == "ALIVE->WEAKENED"
    r2 = arena.judge_round("TEST-B", 2, 60, -0.2, 0, 10**9, death_fingerprint="CALM|UP|mid")
    assert r2["transition"] == "WEAKENED->DEAD"
    tombs = [t for t in store.seed_bank() if t["variant_id"] == "TEST-B"]
    assert len(tombs) == 1 and tombs[0]["death_fingerprint"] == "CALM|UP|mid"
    with pytest.raises(ValueError):
        arena.judge_round("TEST-B", 3, 60, 1.0, 0, 10**9)


def test_clean_window_resets_strikes():
    from app.evo import arena
    store.birth("TEST-C", "c", {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
                                "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False})
    arena.judge_round("TEST-C", 1, 60, -0.4, 0, 10**9)
    r = arena.judge_round("TEST-C", 2, 60, 0.8, 0, 10**9)
    assert r["status"] == "ALIVE" and r["strikes"] == 0


def test_starvation_strikes_first():
    from app.evo import arena
    store.birth("TEST-D", "d", {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
                                "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False})
    r = arena.judge_round("TEST-D", 1, 60, 0.2, 10**9, 10**6)
    assert r["transition"] == "ALIVE->WEAKENED"
    assert any("starvation" in x for x in r["reasons"])


def test_allocation_sums_and_halves_weakened():
    from app.evo import arena
    w = arena.allocate({"a": 1.0, "b": 0.5, "c": -0.3},
                       {"a": "ALIVE", "b": "WEAKENED", "c": "ALIVE"})
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["c"] == 0.0 and w["b"] < w["a"]
    w2 = arena.allocate({"a": -1.0}, {"a": "ALIVE"})
    assert w2 == {"a": 1.0}  # all-negative fallback, no div-zero


def test_resurrection_on_exact_match_only():
    from app.evo import arena
    store.birth("TEST-E", "e", {"topK": 30, "veto_strictness": 1.0, "vix_gate": "on",
                                "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False})
    arena.judge_round("TEST-E", 1, 60, -1.0, 0, 10**9, death_fingerprint="STRESSED|DOWN|low")
    arena.judge_round("TEST-E", 2, 60, -1.0, 0, 10**9, death_fingerprint="STRESSED|DOWN|low")
    assert arena.resurrect_if_matching("CALM|UP|high", "TEST-E2", "e2") is None
    r = arena.resurrect_if_matching("STRESSED|DOWN|low", "TEST-E2", "e2")
    assert r["transition"] == "DEAD->WEAKENED(probation)"
    v = store.get("TEST-E2")
    assert v["status"] == "WEAKENED" and v["probation"] is True
    # probation re-die: one strike kills immediately
    r2 = arena.judge_round("TEST-E2", 1, 60, -0.1, 0, 10**9, death_fingerprint="STRESSED|DOWN|low")
    assert r2["transition"] == "probation->DEAD"


def test_population_cap_and_children():
    from app.evo import arena
    g = {"topK": 50, "veto_strictness": 1.0, "vix_gate": "on",
         "gross_cap": 1.0, "turnover_delta": 0.015, "veto_off": False}
    for i in range(8):
        store.birth(f"TEST-F{i}", f"f{i}", g)
    with pytest.raises(ValueError):
        store.birth("TEST-F8", "f8", g)
    kids = arena.propose_children("TEST-F0", max_children=2)
    assert len(kids) <= 2
    for k in kids:
        Genome(**k).validate()
        assert k["veto_off"] is False


def test_no_llm_in_evo_package():
    import pathlib
    for p in (pathlib.Path("app/evo")).glob("*.py"):
        src = p.read_text(encoding="utf-8").lower()
        assert "gateway" not in src and "complete_json" not in src, p.name
        assert "import openai" not in src and "anthropic" not in src, p.name


def test_trailing_ir_math():
    from app.evo.judge import trailing_ir
    assert trailing_ir([]) == 0.0
    assert trailing_ir([0.01]) == 0.0
    assert trailing_ir([0.01] * 60) == 0.0  # zero variance -> 0, never inf
    assert trailing_ir([0.01, -0.005] * 30) > 0
