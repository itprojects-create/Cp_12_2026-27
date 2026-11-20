"""Veto overlay: deterministic whipsaw/knife filter over core targets (Day 4, prereg).

Contract (data/prereg_overlay_retry.md): may ONLY veto/resize within
[0, core_size]. Never adds direction, never increases size. All inputs
PIT-clean (bars [:t+1] only).
"""
from __future__ import annotations


def breadth_pct(name_closes: dict[str, list[float]], t: int, ma: int = 50) -> float:
    """% of names with close[t] > MA50[t]. Missing bars count as not-above."""
    n_up = 0
    n_tot = 0
    for cs in name_closes.values():
        if t >= len(cs) or t + 1 < ma:
            continue
        window = cs[max(0, t - ma + 1):t + 1]
        if len(window) < ma:
            continue
        n_tot += 1
        if cs[t] > sum(window) / len(window):
            n_up += 1
    return (n_up / n_tot) if n_tot else 0.5


def veto_fraction(regime: str, breadth: float, ret_5d_pct: float,
                   dist_from_high_pct: float, blackout_dense: bool = False) -> float:
    """Frozen veto table (prereg). Returns fraction in [0,1]."""
    # Blowoff: extended into high on short momentum => full veto new longs
    if dist_from_high_pct > -0.5 and ret_5d_pct > 8.0:
        return 1.0
    if regime == "STRESSED" and breadth < 0.40:
        return 1.0
    if regime == "ELEVATED" and breadth < 0.40:
        return 0.5
    if blackout_dense:
        return 0.5
    return 0.0


def apply_veto(core_targets: dict[str, float], vetoes: dict[str, float]) -> dict[str, float]:
    """final = core_size * (1 - veto). Never increases, never flips."""
    out = {}
    for nm, size in core_targets.items():
        v = min(1.0, max(0.0, vetoes.get(nm, 0.0)))
        final = size * (1.0 - v)
        assert 0.0 <= final <= size + 1e-12, "veto must only shrink"
        out[nm] = final
    return out


_DIR_OF_ACTION = {"buy": "long", "sell": "short", "hold": "flat"}


def llm_overlay_size(core_size: float, core_direction: str,
                     llm_action: str, llm_size: float) -> float:
    """ENFORCED money-path boundary: the LLM may only veto or resize a
    deterministic-core target. It can never originate direction and can never
    increase size.

    Rationale (evidence, not preference): the live LLM pipeline never beat a
    trivial constant rule (11/11 clean runs, `beats_best_constant=False`) and the
    deterministic trend rule failed its out-of-sample read too (H1, 0.111 vs
    0.556). The only audited positive number is the deterministic core. So per
    `data/prereg_overlay_retry.md` the LLM is demoted to a veto/resize/
    explainability layer over the core, and this function is the code-level
    guarantee of that contract.

    Rules (all shrink-only, in [0, core_size]):
      - core_size <= 0 or core_direction == "flat" -> 0.0 (nothing to overlay).
      - LLM action OPPOSITE the core direction      -> 0.0 (veto; never flip).
      - LLM action == "hold" (abstain)              -> core_size (no objection;
        an uncertain LLM must NOT silently kill every core trade — the m11
        always-hold failure mode).
      - LLM action AGREES                            -> min(core_size, llm_size)
        (resize down; llm_size <= 0 is treated as a full veto).
    """
    core_size = float(core_size)
    if core_size <= 0.0 or core_direction == "flat":
        return 0.0
    llm_dir = _DIR_OF_ACTION.get(llm_action, "flat")
    if llm_dir == "flat":
        return core_size
    if llm_dir != core_direction:
        return 0.0
    if llm_size <= 0.0:
        return 0.0
    final = min(core_size, float(llm_size))
    assert 0.0 <= final <= core_size + 1e-12, "LLM overlay must only shrink"
    assert (final == 0.0 or _DIR_OF_ACTION.get(llm_action) == core_direction), \
        "LLM overlay must never flip direction"
    return final


def apply_llm_overlay(core_targets: dict[str, float],
                      llm_views: dict[str, dict],
                      *, enabled: bool | None = None,
                      experimental_tag: str = "") -> tuple[dict[str, float], dict]:
    """Production overlay switch (governance R2, migration §23 A/B/C).

    - OFF (default; `LLM_OVERLAY_ENABLED=false`): returns the deterministic
      targets untouched — the no-LLM control. `llm_views` are ignored entirely
      (not even read for sizing), so a disabled overlay cannot leak LLM
      influence into capital.
    - ON: requires a non-empty `experimental_tag` (R2: tagged, measurable vs
      control) and composes each view via llm_overlay_size (veto/resize only).
      Views missing for a name, or missing keys, mean "no LLM view" -> core
      stands (an absent LLM must not kill core trades).

    `llm_views[name]` = {"action": buy|sell|hold, "size": float,
    "core_direction": long|short}. Returns (finals, report).
    """
    if enabled is None:
        from app.config import settings
        enabled = bool(settings.LLM_OVERLAY_ENABLED)
    if not enabled:
        return dict(core_targets), {"overlay": "off",
                                    "note": "no-LLM control; deterministic targets stand",
                                    "n_names": len(core_targets),
                                    "n_vetoed": 0, "n_resized": 0, "n_untouched": len(core_targets)}
    if not experimental_tag:
        raise ValueError("LLM overlay requires an experimental tag (R2: tagged + measured vs control)")
    finals: dict[str, float] = {}
    n_vetoed = n_resized = n_untouched = 0
    for nm, size in core_targets.items():
        view = llm_views.get(nm)
        if not view or not all(k in view for k in ("action", "size", "core_direction")):
            finals[nm] = size
            n_untouched += 1
            continue
        final = llm_overlay_size(size, view["core_direction"], view["action"],
                                 float(view["size"]))
        finals[nm] = final
        if final == 0.0 and size > 0.0:
            n_vetoed += 1
        elif final < size:
            n_resized += 1
        else:
            n_untouched += 1
    return finals, {"overlay": "on-experimental", "tag": experimental_tag,
                    "n_names": len(core_targets), "n_vetoed": n_vetoed,
                    "n_resized": n_resized, "n_untouched": n_untouched}
