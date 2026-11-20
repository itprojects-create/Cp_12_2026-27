"""Money-path boundary (step 3): the LLM may only veto/resize a core target.

Enforces the prereg overlay contract in code: the LLM session can never originate
direction and can never increase size on the money path. The deterministic core
(+6.15% CAGR, Sharpe 0.705 / MaxDD 12.46% in v3) is the direction source; the LLM
is a veto/resize/explainability layer.
"""
from __future__ import annotations

import pytest

from app.core.overlay import llm_overlay_size


def test_llm_can_never_increase_size():
    # confident LLM proposes a bigger size than the core -> core size stands
    assert llm_overlay_size(0.05, "long", "buy", 0.10) == 0.05


def test_llm_may_resize_down_when_agreeing():
    assert llm_overlay_size(0.05, "long", "buy", 0.02) == 0.02
    assert llm_overlay_size(0.04, "short", "sell", 0.03) == 0.03


def test_llm_opposite_direction_is_a_veto_never_a_flip():
    assert llm_overlay_size(0.05, "long", "sell", 0.05) == 0.0
    assert llm_overlay_size(0.04, "short", "buy", 0.04) == 0.0


def test_llm_hold_is_abstention_not_a_veto():
    # an uncertain LLM must not silently kill every core trade (m11 failure mode)
    assert llm_overlay_size(0.05, "long", "hold", 0.0) == 0.05


def test_zero_size_llm_agreeing_is_a_full_veto():
    assert llm_overlay_size(0.05, "long", "buy", 0.0) == 0.0


def test_no_core_target_means_nothing_to_overlay():
    assert llm_overlay_size(0.0, "long", "buy", 0.05) == 0.0
    assert llm_overlay_size(0.05, "flat", "buy", 0.05) == 0.0


@pytest.mark.parametrize("llm_size", [0.0, 0.01, 0.05, 0.09, 0.5])
@pytest.mark.parametrize("action", ["buy", "sell", "hold"])
def test_boundary_invariant_never_exceeds_core(llm_size, action):
    core = 0.05
    final = llm_overlay_size(core, "long", action, llm_size)
    assert 0.0 <= final <= core


def test_paper_path_is_zero_llm_by_construction():
    # Money path = scripts/paper_trade_10L.py replays frozen run_core_v4 with a
    # share ledger. It must never import the LLM pipeline (agents/gateway) nor
    # consult DIRECTION_POLICY — paper P&L in data/paper_10L_*.json is audited
    # as zero-LLM. llm_overlay_size above remains the SOLE composition point
    # should any future caller wire an LLM decision onto a core target.
    import pathlib
    src = pathlib.Path("scripts/paper_trade_10L.py").read_text(encoding="utf-8")
    for forbidden in ("from app.agents", "from app.gateway", "call_json",
                      "run_session", "DIRECTION_POLICY", "codecraft", "openrouter"):
        assert forbidden not in src, f"money path must not contain {forbidden!r}"
