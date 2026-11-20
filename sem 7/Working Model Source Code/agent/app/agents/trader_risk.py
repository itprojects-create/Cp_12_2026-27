"""Phase 6: Trader (luna) -> Risk panel 3x (luna) -> Portfolio Manager (sonnet) -> FinalDecision."""
from __future__ import annotations
from datetime import datetime
from app import schemas as S
from app.agents._util import call_json
from app.data.base import apply_cost
from app.data.yfinance_provider import YFinanceProvider

MAX_POSITION_PCT = 0.10
# Prereg prereg_llm_direction_fix.md F2: LLM never sizes — deterministic fixed base.
# Ignores dec.size / proposal.size_pct magnitude (conviction carries no signal,
# Spearman +0.033; gate inversion came from LLM-sized over-trades).
FIXED_BASE_SIZE = 0.025

def _price(instrument: str, as_of: datetime) -> float:
    df = YFinanceProvider().ohlcv(instrument, as_of, "1d", lookback=5)
    c = df["Close"].dropna()
    return float(c.iloc[-1])

def run_trader(instrument: str, thesis: S.Thesis, challenge: S.Challenge,
               as_of: datetime, session_id: str, portfolio_block: str = "") -> S.TradeProposal:
    px = _price(instrument, as_of)
    direction = {"long": "long", "short": "short", "flat": "flat"}[thesis.direction]
    system = ("You are the Trader. Convert the thesis into ONE sized, executable proposal. "
              "Flat thesis -> direction=flat size_pct=0. Respect stop/target on the correct side of entry. "
              "If a portfolio block is given, size against it (adding to a full position is not opening new). "
              "Return ONLY TradeProposal JSON: {instrument, direction, size_pct, entry, stop, target}.")
    user = (f"instrument={instrument} price={px:.2f} as_of={as_of.isoformat()}\n"
            f"thesis={thesis.model_dump_json()}\nchallenge={challenge.status.value}: {challenge.reasons}\n"
            f"max_position_pct={MAX_POSITION_PCT}"
            + (f"\n{portfolio_block}" if portfolio_block else ""))
    return call_json("trader", session_id, system, user, S.TradeProposal, {"instrument": instrument})

_RISK_SYS = ("You are a Risk debater ({persona}). Stress-test the proposal: size vs 10% max, "
             "stop distance, thesis conviction vs challenge status. "
             "Return ONLY RiskVerdict JSON with keys approve, adjusted_size, notes.")

def run_risk_panel(proposal: S.TradeProposal, thesis: S.Thesis, challenge: S.Challenge,
                   session_id: str, portfolio_block: str = "") -> dict[str, S.RiskVerdict]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import hashlib
    import json
    from app.config import settings
    from app.agents.graph import _load_ckpt, _save_ckpt, log_event
    ctx = (f"proposal={proposal.model_dump_json()}\nthesis conviction={thesis.conviction} "
           f"direction={thesis.direction}\nchallenge={challenge.status.value}\nmax_position_pct={MAX_POSITION_PCT}"
           + (f"\n{portfolio_block}" if portfolio_block else ""))
    personas = {"risk_agg": "AGGRESSIVE: favor edge, trim only for hard breaches",
                "risk_con": "CONSERVATIVE: default to reject/ halve unless thesis is strong and challenge HEALTHY",
                "risk_neu": "NEUTRAL: balance edge vs risk mechanically"}
    # Each persona receives the same immutable context; no reviewer depends on another.
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        pending = {}
        for role, persona in personas.items():
            system = _RISK_SYS.format(persona=persona)
            # Retry-manager can change a proposal in the same session. Reuse is
            # valid only for identical evidence, prompts and model configuration.
            digest = hashlib.sha256(json.dumps([system, ctx, settings.PROMPT_VERSION,
                        settings.role_config(role)], sort_keys=True).encode()).hexdigest()[:16]
            stage = f"risk:{role}:{digest}"
            hit = _load_ckpt(session_id, stage)
            if hit:
                results[role] = S.RiskVerdict.model_validate_json(hit)
            else:
                pending[executor.submit(call_json, role, session_id, system, ctx, S.RiskVerdict)] = (role, stage)
        failure = None
        for future in as_completed(pending):
            role, stage = pending[future]
            try:
                result = future.result()
                results[role] = result
                _save_ckpt(session_id, stage, result.model_dump_json())
                log_event(session_id, "risk", role, "done")
            except Exception as error:
                failure = failure or error
        if failure:
            raise failure
    return {role: results[role] for role in personas}

def run_pm(instrument: str, thesis: S.Thesis, challenge: S.Challenge, proposal: S.TradeProposal,
           verdicts: dict[str, S.RiskVerdict], thesis_version: int, session_id: str,
           regime: str | None = None, market_trend: str | None = None,
           direction_policy: str | None = None, portfolio_block: str = "") -> S.FinalDecision:
    v = "\n".join(f"{k}: approve={x.approve} size={x.adjusted_size} notes={x.notes}" for k, x in verdicts.items())
    system = ("You are the Portfolio Manager. Final approve/reject. Conservative verdict or "
              "BROKEN challenge must shrink or block size. Flat thesis -> action=hold size=0. "
              "DATA_UNAVAILABLE evidence is missing data, never bearish evidence. "
              "Return ONLY FinalDecision JSON: {action, size, rationale, thesis_version}.")
    user = (f"instrument={instrument}\nthesis={thesis.model_dump_json()}\nchallenge={challenge.status.value}\n"
            f"proposal={proposal.model_dump_json()}\nrisk:\n{v}\nthesis_version={thesis_version}\n"
            f"cost_note=round-trip {0.21}% applied at paper fill"
            + (f"\n{portfolio_block}" if portfolio_block else ""))
    dec = call_json("portfolio_manager", session_id, system, user, S.FinalDecision,
                    {"thesis_version": thesis_version,
                     # Authority is a code-owned governance label, never an LLM
                     # opinion. Providers sometimes invent a role name here.
                     "authority": "RESEARCH_ONLY", "cannot_create_position": True,
                     "cannot_reverse_position": True, "cannot_increase_exposure": True})

    rationale = dec.rationale
    if regime is None:
        regime = "CALM"
    trend = market_trend or "UNKNOWN"

    if (direction_policy or "llm") == "trend":
        # Pre-registered H1 (data/prereg_v4_trend_direction.md): the PIT index trend
        # sets direction; the LLM only sizes (via the proposal) and vetoes on
        # flat/BROKEN. Deterministic, after all LLM reasoning — no agent stage can
        # override it. Sizing is fixed (never LLM-inflated).
        base = min(MAX_POSITION_PCT, proposal.size_pct if proposal.size_pct > 0 else 0.03)
        if thesis.direction == "flat":
            size, action = 0.0, "hold"
            tag = " [CODE POLICY: no edge — flat thesis]"
        elif challenge.status == S.ThesisStatus.BROKEN:
            size, action = 0.0, "hold"
            tag = " [CODE POLICY: veto — BROKEN challenge]"
        elif trend == "UP":
            size, action = base, "buy"
            tag = " [CODE POLICY: direction from index trend UP]"
        elif trend == "DOWN":
            size, action = base, "sell"
            tag = " [CODE POLICY: direction from index trend DOWN]"
        else:
            size, action = 0.0, "hold"
            tag = f" [CODE POLICY: no edge — index trend {trend}]"
        rationale = rationale[:2000 - len(tag)] + tag
        return S.FinalDecision(action=action, size=size, rationale=rationale, thesis_version=thesis_version)

    # ---- default "llm" policy: guardrails over the pipeline's own directional call ----
    # deterministic sizing (prereg_llm_direction_fix.md F2): code owns size, not the LLM.
    # Direction idea comes from thesis/dec.action; magnitude is FIXED_BASE_SIZE.
    size = FIXED_BASE_SIZE if dec.action in ("buy", "sell") else 0.0
    if thesis.direction == "flat" or challenge.status == S.ThesisStatus.BROKEN:
        size = 0.0
    action = "hold" if size == 0.0 else dec.action
    # M3 VIX regime gate (code-level, after ALL LLM reasoning — no agent stage can
    # override it). Only MOMENTUM_CONTINUATION theses are gated; every other
    # mechanism passes through untouched. `regime` comes from regime_at() via the
    # caller; None (unknown) defaults to CALM — never gate blind. The tag in
    # rationale mirrors the BROKEN guardrail's auditability in the session log.
    tag = ""
    if thesis.mechanism_type == S.MechanismType.MOMENTUM_CONTINUATION:
        if regime == "STRESSED":
            size, action = 0.0, "hold"
            tag = " [CODE GUARDRAIL: momentum thesis blocked — STRESSED VIX regime]"
        elif regime == "ELEVATED":
            size = size * 0.5
            if size == 0.0:
                action = "hold"
            tag = " [CODE GUARDRAIL: momentum thesis sized down 50% — ELEVATED VIX regime]"
    # Counter-trend guardrail (M4): symmetric, code-level, applied after ALL LLM
    # reasoning so no agent stage can override it. Do NOT take a LONG into a
    # confirmed index downtrend, nor a SHORT into a confirmed uptrend — the exact
    # failure mode measured in data/baseline_analysis.json (agent under-performs a
    # constant rule in both directions by fighting the market trend). RANGE /
    # UNKNOWN (missing index data) never gate. Only the thesis direction is
    # checked; sizing is untouched on pass-through.
    if (thesis.direction == "long" and trend == "DOWN") or \
       (thesis.direction == "short" and trend == "UP"):
        size, action = 0.0, "hold"
        tag += f" [CODE GUARDRAIL: counter-trend {thesis.direction} blocked — index trend {trend}]"
    tag += " [CODE SIZING: fixed 0.025, LLM size ignored]"
    rationale = rationale[:2000 - len(tag)] + tag  # keep the audit tag intact
    return S.FinalDecision(action=action, size=size, rationale=rationale, thesis_version=thesis_version)
