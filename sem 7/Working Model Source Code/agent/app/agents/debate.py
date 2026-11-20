"""Phase 4 debate: Bull vs Bear, bounded rounds, explicit converge/timeout exit. Luna."""
from __future__ import annotations
from app import schemas as S
from app.agents._util import call_json, evidence_ledger


def _turn(role, session_id, user, stance):
    import hashlib
    import json
    from app.config import settings
    from app.agents.graph import _load_ckpt, _save_ckpt
    digest = hashlib.sha256(json.dumps([SYSTEM, user, stance, settings.PROMPT_VERSION,
                settings.role_config(role)], sort_keys=True).encode()).hexdigest()[:16]
    stage = f"debate:{role}:{digest}"
    hit = _load_ckpt(session_id, stage)
    if hit:
        return S.DebateTurn.model_validate_json(hit)
    result = call_json(role, session_id, SYSTEM, user, S.DebateTurn, {"stance": stance})
    _save_ckpt(session_id, stage, result.model_dump_json())
    return result

SYSTEM = ("You argue ONE side (long or short) from the analyst reports. "
          "Return ONLY DebateTurn JSON: {stance, argument, rebuttal_to, confidence_delta}. "
          "stance is 'long' if you are Bull else 'short'. rebuttal_to = opponent's key point or '' on round 1.")

def _digest(reports: list[S.AnalystReport]) -> str:
    # Root-cause fix (data/prereg_manager_evidence.md): the debaters must see the
    # same structured signals + code-computed tally the Manager sees, not prose only.
    return evidence_ledger(reports)

def run_debate(reports: list[S.AnalystReport], session_id: str, rounds: int = 2) -> list[S.DebateTurn]:
    digest = _digest(reports)
    turns: list[S.DebateTurn] = []
    last_bear, last_bull = "", ""
    for r in range(1, rounds + 1):
        bull = _turn("bull", session_id,
                         f"ROUND {r}/{rounds}. You are BULL (long).\nanalysts:\n{digest}\n"
                         f"bear_last: {last_bear or '(none)'}", "long")
        turns.append(bull)
        bear = _turn("bear", session_id,
                         f"ROUND {r}/{rounds}. You are BEAR (short).\nanalysts:\n{digest}\n"
                         f"bull_last: {bull.argument}", "short")
        turns.append(bear)
        last_bull, last_bear = bull.argument, bear.argument
        # converge exit: both sides barely move conviction
        if abs(bull.confidence_delta) < 0.05 and abs(bear.confidence_delta) < 0.05:
            break
    return turns
