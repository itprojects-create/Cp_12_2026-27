"""Forward signal pipeline (W6.2): every attempt is recorded, never selective.

For every universe candidate at every session cutoff the pipeline writes
exactly one of:
  SIGNAL_DECISION     a tradable decision (side + horizon), or
  NO_SIGNAL           the code-owned answer "no eligible strategy", or
  ABSTENTION          the model/evaluator declined to answer, or
  ELIGIBILITY_FAILURE the decision failed an eligibility gate.

Outcomes generated after the cutoff are never carried into the decision
record.  The stream must already be sealed (preregistration first) before any
decision is evaluated.  Paper intents are only minted when the admissibility
gate allows paper intent AND the book is authorised (fixture or approved).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from quantplus_intelligence.research_v3.wave5_common import parse_aware_timestamp

from .contracts import (
    DECISION_ABSTAIN,
    DECISION_ELIGIBILITY_FAILURE,
    DECISION_NO_SIGNAL,
    DECISION_SIGNAL,
    MATURITY_ENGINEERING_FIXTURE,
    AbstentionRecord,
    EligibilityFailureRecord,
    NoSignalRecord,
    SignalDecision,
)
from .preregistration import (
    ForwardProtocol,
    admissibility,
    stream_is_sealed_before_first_signal,
)

Evaluator = Callable[[dict, str], dict]
"""evaluator(candidate, decision_cutoff) -> dict with keys:
decision: SIGNAL|NO_SIGNAL|ABSTAIN (+ side/score/target_weight/horizon when SIGNAL)
answerable: bool
reason_codes: tuple[str, ...]
The evaluator receives ONLY candidate identity and the cutoff; any data access
it performs is its own responsibility and must respect the cutoff."""


class SignalPipeline:
    def __init__(self, ledger, stream_id: str, protocol: ForwardProtocol | None,
                 evaluator: Evaluator | None = None, *, fixture: bool = False):
        self.ledger = ledger
        self.stream_id = stream_id
        self.protocol = protocol
        self.evaluator = evaluator
        self.fixture = fixture
        self._gate = (admissibility(protocol) if protocol else {
            "status": "NO_ELIGIBLE_STRATEGY",
            "reasons": ["NO_PROTOCOL_NULL_BASELINE"],
            "paper_intent_allowed": False,
            "observational_logging_allowed": True,
            "authority": "RESEARCH_ONLY"})

    def _maturity(self) -> str:
        return MATURITY_ENGINEERING_FIXTURE if self.fixture \
            else "OBSERVED_FORWARD_RESEARCH"

    def evaluate(self, candidates: Iterable[dict], decision_cutoff: str,
                 session_date: str, *, recorded_at: str) -> list[dict]:
        """Evaluate every candidate at one cutoff; return the record payloads.

        Raises if the stream is not sealed before the first signal.
        """
        if not stream_is_sealed_before_first_signal(self.ledger, self.stream_id):
            raise PermissionError(
                "STREAM_NOT_SEALED: preregistration must precede the first signal")
        parse_aware_timestamp(decision_cutoff, "decision_cutoff")
        recorded = parse_aware_timestamp(recorded_at, "recorded_at")
        cutoff = parse_aware_timestamp(decision_cutoff, "decision_cutoff")
        if recorded < cutoff:
            raise ValueError("recorded_at cannot precede decision_cutoff")
        outcomes: list[dict] = []
        for candidate in candidates:
            outcomes.append(self._evaluate_one(candidate, decision_cutoff,
                                               session_date, recorded_at))
        return outcomes

    def _evaluate_one(self, candidate: dict, decision_cutoff: str,
                      session_date: str, recorded_at: str) -> dict:
        symbol = candidate.get("symbol")
        if not symbol:
            raise ValueError("every universe candidate needs a symbol")
        isin = candidate.get("isin")
        candidate_id = candidate.get("candidate_id", "null-baseline")
        base = {"stream_id": self.stream_id,
                "recorded_at": recorded_at,
                "maturity": self._maturity(),
                "decision_cutoff": decision_cutoff,
                "session_date": session_date}
        if self.evaluator is None:
            record = NoSignalRecord(**base, symbol=symbol,
                                    candidate_id=candidate_id,
                                    reason="NO_ELIGIBLE_STRATEGY",
                                    detail="null baseline: no eligible strategy "
                                           "registered for this stream")
            self._write("NO_SIGNAL", record, {
                "stream": self.stream_id, "cutoff": decision_cutoff,
                "symbol": symbol, "candidate": candidate_id})
            return record.payload()
        raw = self.evaluator(candidate, decision_cutoff)
        kind = raw.get("decision", DECISION_NO_SIGNAL)
        answerable = raw.get("answerable", kind != DECISION_ABSTAIN)
        reasons = tuple(raw.get("reason_codes", ()))
        if kind == DECISION_SIGNAL and answerable:
            record = SignalDecision(
                **base, symbol=symbol, isin=isin, candidate_id=candidate_id,
                strategy_spec_hash=(self.protocol.strategy_spec_hash
                                    if self.protocol else None),
                model_version=(self.protocol.model_version if self.protocol
                               else None),
                decision=DECISION_SIGNAL,
                side=raw["side"], target_weight=raw.get("target_weight"),
                horizon_sessions=raw.get("horizon_sessions"),
                score=raw.get("score"), reason_codes=reasons,
                calendar_version=(self.protocol.reserve_settlement_model
                                  if self.protocol else None))
            self._write("SIGNAL_DECISION", record, {
                "stream": self.stream_id, "cutoff": decision_cutoff,
                "symbol": symbol, "candidate": candidate_id})
        elif kind == DECISION_ABSTAIN or answerable is False:
            record = AbstentionRecord(
                **base, symbol=symbol, candidate_id=candidate_id,
                abstention_kind=raw.get("abstention_kind", "MODEL_ABSTAINED"),
                detail=raw.get("detail", ""))
            self._write("ABSTENTION", record, {
                "stream": self.stream_id, "cutoff": decision_cutoff,
                "symbol": symbol, "candidate": candidate_id})
        elif kind in (DECISION_NO_SIGNAL, DECISION_ELIGIBILITY_FAILURE):
            record = (NoSignalRecord if kind == DECISION_NO_SIGNAL
                      else EligibilityFailureRecord)(
                **base, symbol=symbol, candidate_id=candidate_id,
                **({"reason": raw.get("reason", "NO_SIGNAL")}
                   if kind == DECISION_NO_SIGNAL else
                   {"stage": raw.get("stage", "DECISION"),
                    "blocker": raw.get("blocker", "ELIGIBILITY_GATE_FAILED")}),
                detail=raw.get("detail", ""))
            event = ("NO_SIGNAL" if kind == DECISION_NO_SIGNAL
                     else "ELIGIBILITY_FAILURE")
            self._write(event, record, {
                "stream": self.stream_id, "cutoff": decision_cutoff,
                "symbol": symbol, "candidate": candidate_id})
        else:
            raise ValueError(f"evaluator returned unknown decision {kind!r}")
        return record.payload()

    def _write(self, event_type: str, record, semantic_key: dict) -> dict:
        event, _ = self.ledger.append_record(event_type, record, semantic_key)
        return event

    def paper_intent_allowed(self) -> bool:
        return bool(self._gate.get("paper_intent_allowed"))

    def gate(self) -> dict:
        return dict(self._gate)


def pit_value(value: Any, *, available_at: str, decision_cutoff: str,
              source_id: str) -> Any:
    """Return a value only when it was available by the decision cutoff.

    This tiny helper is deliberately used by injected evaluators/tests for
    delayed news and bars. A vendor's old economic timestamp is irrelevant: the
    strategy clock is ``available_at`` (first usable possession).
    """
    available = parse_aware_timestamp(available_at, "available_at")
    cutoff = parse_aware_timestamp(decision_cutoff, "decision_cutoff")
    if available > cutoff:
        raise ValueError(f"FUTURE_INPUT_BLOCKED:{source_id}")
    return value
