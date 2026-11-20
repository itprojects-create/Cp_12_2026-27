"""Typed, immutable records for the V3.1 forward-only research stream (W6).

Every record is a frozen dataclass with an explicit evidence surface: decision
cutoff, provider/published/available/recorded timestamps, source identity and
reason codes.  Wall clocks are evidence only where the handoff says so; all
money is integer paise; no record carries an outcome generated after the
decision cutoff.

Three maturity labels separate evidence classes everywhere:
  ENGINEERING_FIXTURE         synthetic inputs/execution scenarios for tests
  OBSERVED_FORWARD_RESEARCH   after-seal time-stamped observations + signals
  ELIGIBLE_PAPER_PORTFOLIO    operator-approved paper-only candidate accounting
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any

from quantplus_intelligence.research_v3.wave5_common import (
    is_sha256,
    parse_aware_timestamp,
    semantic_sha256,
)

IST = timezone(timedelta(hours=5, minutes=30))

MATURITY_ENGINEERING_FIXTURE = "ENGINEERING_FIXTURE"
MATURITY_OBSERVED_FORWARD = "OBSERVED_FORWARD_RESEARCH"
MATURITY_ELIGIBLE_PAPER = "ELIGIBLE_PAPER_PORTFOLIO"
MATURITY_LABELS = frozenset({
    MATURITY_ENGINEERING_FIXTURE, MATURITY_OBSERVED_FORWARD, MATURITY_ELIGIBLE_PAPER})

# Code-owned admissibility gate outcomes (never a model verdict).
ADMISSIBILITY_PAPER_ELIGIBLE = "PAPER_ELIGIBLE"
ADMISSIBILITY_RESEARCH_ONLY = "RESEARCH_ONLY"
ADMISSIBILITY_NO_ELIGIBLE_STRATEGY = "NO_ELIGIBLE_STRATEGY"
ADMISSIBILITY_DATA_BLOCKED = "DATA_BLOCKED"
ADMISSIBILITY_OPERATOR_APPROVAL_REQUIRED = "OPERATOR_APPROVAL_REQUIRED"

DECISION_SIGNAL = "SIGNAL"
DECISION_NO_SIGNAL = "NO_SIGNAL"
DECISION_ABSTAIN = "ABSTAIN"
DECISION_ELIGIBILITY_FAILURE = "ELIGIBILITY_FAILURE"
DECISION_UNAVAILABLE = "UNAVAILABLE"

INTENT_MARKET = "MARKET"
INTENT_LIMIT = "LIMIT"
INTENT_STOP = "STOP"
ORDER_TYPES = frozenset({INTENT_MARKET, INTENT_LIMIT, INTENT_STOP})

FILL_FILLED = "FILLED"
FILL_PARTIAL = "PARTIAL_FILL"
FILL_UNFILLED = "UNFILLED"
FILL_CANCELLED = "CANCELLED"
FILL_EXPIRED = "EXPIRED"
FILL_REJECTED = "REJECTED"
FILL_NOT_EXECUTED = "NOT_EXECUTED"
FILL_NO_TRADE = "NO_TRADE"

REASON_NO_ELIGIBLE_STRATEGY = "NO_ELIGIBLE_STRATEGY"
REASON_OPERATOR_APPROVAL_REQUIRED = "OPERATOR_APPROVAL_REQUIRED"
REASON_QUOTE_STALE = "QUOTE_STALE"
REASON_QUOTE_MISSING = "QUOTE_MISSING"
REASON_SESSION_CLOSED = "SESSION_CLOSED_UNVERIFIED_OR_HOLIDAY"
REASON_SYMBOL_UNRESOLVED = "SYMBOL_UNRESOLVED"
REASON_SUSPENDED = "SUSPENDED_OR_HALTED"
REASON_ACTION_PENDING = "CORPORATE_ACTION_PENDING_UNVERIFIED"
REASON_FEE_SCHEDULE_UNKNOWN = "FEE_SCHEDULE_UNKNOWN_FOR_DATE"
REASON_INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_OBSERVED_LIQUIDITY"
REASON_CASH_SHORT = "CASH_OR_SETTLED_SHARES_SHORT"
REASON_RIGHTS_MISSING = "SOURCE_RIGHTS_MISSING"
REASON_LIMIT_NOT_TOUCHED = "LIMIT_NOT_TOUCHED"
REASON_STOP_NOT_TRIGGERED = "STOP_NOT_TRIGGERED"
REASON_FUTURE_QUOTE = "QUOTE_TIMESTAMP_AFTER_RECORD_TIME"
REASON_OCO_CANCELLED = "OCO_OTHER_LEG_FILLED"
REASON_ACTION_ADJUSTMENT_CANCELLED = "CORPORATE_ACTION_ADJUSTMENT_CANCELLED_OPEN_ORDER"
REASON_EXPIRED = "DAY_ORDER_EXPIRED_END_OF_SESSION"

FORBIDDEN_FORWARD_LABELS = frozenset({
    "FORECAST", "FUTURE_PROBABILITY", "EXPECTED_RETURN", "LIVE_EXECUTABLE",
    "PIT_VALIDATED", "PROFITABLE", "VALIDATED_ALPHA",
})


def ist_presentation(utc_iso: str) -> str:
    """Explicit Asia/Kolkata presentation of a stored UTC timestamp."""
    return parse_aware_timestamp(utc_iso, "timestamp").astimezone(IST).isoformat()


def _check_iso(value: str, name: str) -> None:
    parse_aware_timestamp(value, name)


def _check_utc(value: str, name: str) -> None:
    parsed = parse_aware_timestamp(value, name)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be stored in UTC")


def _check_sha256(value: str | None, name: str) -> None:
    if value is not None and not is_sha256(value):
        raise ValueError(f"{name} must be a full sha256 hex digest")


def _check_nonneg_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer paise amount")


@dataclass(frozen=True, kw_only=True)
class ForwardRecord:
    """Base surface shared by every forward-stream record."""

    stream_id: str
    recorded_at: str                 # exact UTC first-seen in this store
    maturity: str = MATURITY_OBSERVED_FORWARD
    decision_cutoff: str | None = None
    session_date: str | None = None  # exchange session (IST date) if applicable

    def __post_init__(self) -> None:
        if not self.stream_id or not isinstance(self.stream_id, str):
            raise ValueError("stream_id is required")
        _check_utc(self.recorded_at, "recorded_at")
        if self.maturity not in MATURITY_LABELS:
            raise ValueError(f"unknown maturity label {self.maturity!r}")
        if self.decision_cutoff is not None:
            _check_utc(self.decision_cutoff, "decision_cutoff")
            if parse_aware_timestamp(self.recorded_at, "recorded_at") < \
                    parse_aware_timestamp(self.decision_cutoff, "decision_cutoff"):
                raise ValueError("recorded_at cannot precede decision_cutoff")
        if self.session_date is not None and not (
                isinstance(self.session_date, str) and len(self.session_date) == 10):
            raise ValueError("session_date must be an ISO date")

    def base_payload(self) -> dict:
        return {
            "stream_id": self.stream_id,
            "recorded_at": self.recorded_at,
            "maturity": self.maturity,
            "decision_cutoff": self.decision_cutoff,
            "session_date": self.session_date,
        }


def _quote_quality(bid: int | None, ask: int | None, last: int | None) -> str:
    if bid and ask and ask > 0 and bid > 0 and ask >= bid:
        return "BID_ASK_OBSERVED"
    if last and last > 0:
        return "LAST_ONLY"
    return "UNUSABLE"


@dataclass(frozen=True, kw_only=True)
class QuoteObservation(ForwardRecord):
    """One observed (or explicitly fixture) quote for one instrument/session."""

    symbol: str
    isin: str | None = None
    provider: str = "fixture"
    provider_ts: str | None = None       # provider-stamped time of the quote
    available_at: str | None = None      # earliest time the quote was usable
    session_date: str | None = None
    bid_paise: int | None = None
    ask_paise: int | None = None
    last_paise: int | None = None
    volume: int | None = None
    depth_lots: int | None = None
    stale: bool = False
    halted_or_suspended: bool = False
    source_ref: str | None = None
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.symbol:
            raise ValueError("symbol is required")
        for name in ("bid_paise", "ask_paise", "last_paise", "volume", "depth_lots"):
            value = getattr(self, name)
            if value is not None:
                _check_nonneg_int(value, name)
        for name in ("provider_ts", "available_at"):
            value = getattr(self, name)
            if value is not None:
                _check_utc(value, name)
        _check_sha256(self.source_sha256, "source_sha256")
        if self.maturity != MATURITY_ENGINEERING_FIXTURE:
            if self.provider == "fixture":
                raise ValueError("a real forward quote cannot use the fixture provider")
            if not (self.provider_ts and self.available_at and self.source_ref
                    and self.source_sha256):
                raise ValueError(
                    "real forward quotes require provider/available clocks and source provenance")
        if self.bid_paise and self.ask_paise and self.ask_paise < self.bid_paise:
            raise ValueError("ask_paise must be greater than or equal to bid_paise")
        if self.halted_or_suspended and self.last_paise:
            # A halted instrument may carry a last quote, but it must never be
            # silently treated as executable; the fill gate refuses it.
            pass

    @property
    def quote_quality(self) -> str:
        if self.halted_or_suspended:
            return "HALTED_NOT_EXECUTABLE"
        return _quote_quality(self.bid_paise, self.ask_paise, self.last_paise)

    def executable_price_paise(self, side: str, slippage_paise: int = 0) -> int | None:
        """Conservative executable price: ask + slip for buys, bid - slip for sells."""
        if self.halted_or_suspended or self.stale:
            return None
        if side == "BUY":
            ref = self.ask_paise or self.last_paise
            return ref + slippage_paise if ref else None
        if side == "SELL":
            ref = self.bid_paise or self.last_paise
            return ref - slippage_paise if ref and ref > slippage_paise else (
                None if ref is None else max(ref - slippage_paise, 0))
        raise ValueError("side must be BUY or SELL")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "QUOTE_OBSERVATION",
                "symbol": self.symbol, "isin": self.isin, "provider": self.provider,
                "provider_ts": self.provider_ts, "available_at": self.available_at,
                "bid_paise": self.bid_paise, "ask_paise": self.ask_paise,
                "last_paise": self.last_paise, "volume": self.volume,
                "depth_lots": self.depth_lots, "stale": self.stale,
                "halted_or_suspended": self.halted_or_suspended,
                "quote_quality": self.quote_quality,
                "source_ref": self.source_ref, "source_sha256": self.source_sha256}


@dataclass(frozen=True, kw_only=True)
class SignalDecision(ForwardRecord):
    """A recorded decision for one candidate at one cutoff. Outcomes never inside."""

    symbol: str
    isin: str | None = None
    candidate_id: str = "null-baseline"
    strategy_spec_hash: str | None = None
    model_version: str | None = None
    decision: str = DECISION_NO_SIGNAL        # SIGNAL/NO_SIGNAL/ABSTAIN/...
    side: str | None = None                   # BUY/SELL when SIGNAL
    target_weight: float | None = None
    horizon_sessions: int | None = None
    score: float | None = None                # model/pattern score, research only
    reason_codes: tuple[str, ...] = ()
    answerable: bool = True
    calendar_version: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.decision not in {DECISION_SIGNAL, DECISION_NO_SIGNAL, DECISION_ABSTAIN,
                                 DECISION_ELIGIBILITY_FAILURE, DECISION_UNAVAILABLE}:
            raise ValueError(f"unknown decision {self.decision!r}")
        if self.decision == DECISION_SIGNAL and self.side not in ("BUY", "SELL"):
            raise ValueError("SIGNAL requires side BUY/SELL")
        if self.decision == DECISION_SIGNAL and self.answerable is False:
            raise ValueError("SIGNAL must be answerable")
        if self.horizon_sessions is not None and (
                not isinstance(self.horizon_sessions, int) or self.horizon_sessions <= 0):
            raise ValueError("horizon_sessions must be a positive session count")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.target_weight is not None and (
                not math.isfinite(self.target_weight)
                or not 0.0 <= self.target_weight <= 1.0):
            raise ValueError("target_weight must be finite and in [0, 1]")
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("score must be finite")

    @property
    def decision_id(self) -> str:
        return semantic_sha256(self.payload())

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "SIGNAL_DECISION",
                "symbol": self.symbol, "isin": self.isin,
                "candidate_id": self.candidate_id,
                "strategy_spec_hash": self.strategy_spec_hash,
                "model_version": self.model_version, "decision": self.decision,
                "side": self.side, "target_weight": self.target_weight,
                "horizon_sessions": self.horizon_sessions, "score": self.score,
                "reason_codes": list(self.reason_codes), "answerable": self.answerable,
                "calendar_version": self.calendar_version}


@dataclass(frozen=True, kw_only=True)
class PaperIntent(ForwardRecord):
    """Operator-approved (or fixture) paper order intent. Never a broker order."""

    intent_id: str
    symbol: str
    isin: str | None = None
    side: str = "BUY"
    order_type: str = INTENT_MARKET
    quantity: int | None = None
    notional_paise: int | None = None
    limit_paise: int | None = None
    stop_paise: int | None = None
    time_in_force_sessions: int = 1           # DAY by default
    oco_group: str | None = None              # one-cancels-other linkage
    decision: SignalDecision | None = None
    approved_for_paper: bool = False
    approval_ref: str | None = None
    reason_codes: tuple[str, ...] = ()
    risk_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if self.order_type not in ORDER_TYPES:
            raise ValueError(f"unknown order type {self.order_type!r}")
        if self.quantity is not None and (not isinstance(self.quantity, int)
                                          or self.quantity <= 0):
            raise ValueError("quantity must be a positive integer")
        if self.notional_paise is not None:
            _check_nonneg_int(self.notional_paise, "notional_paise")
        if self.limit_paise is not None:
            _check_nonneg_int(self.limit_paise, "limit_paise")
        if self.stop_paise is not None:
            _check_nonneg_int(self.stop_paise, "stop_paise")
        if not self.approved_for_paper and self.maturity == MATURITY_ELIGIBLE_PAPER:
            raise ValueError(
                "ELIGIBLE_PAPER_PORTFOLIO records require an operator approval reference")
        if self.approved_for_paper and not self.approval_ref:
            raise ValueError("approved paper intents must cite an approval_ref")
        if not self.intent_id:
            raise ValueError("intent_id is required")
        if self.quantity is None and self.notional_paise is None:
            raise ValueError("quantity or notional_paise is required")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "PAPER_INTENT", "intent_id": self.intent_id,
                "symbol": self.symbol, "isin": self.isin, "side": self.side,
                "order_type": self.order_type, "quantity": self.quantity,
                "notional_paise": self.notional_paise, "limit_paise": self.limit_paise,
                "stop_paise": self.stop_paise,
                "time_in_force_sessions": self.time_in_force_sessions,
                "oco_group": self.oco_group,
                "decision_ref": self.decision.decision_id
                if self.decision else None,
                "approved_for_paper": self.approved_for_paper,
                "approval_ref": self.approval_ref,
                "reason_codes": list(self.reason_codes),
                "risk_event_ids": list(self.risk_event_ids)}


@dataclass(frozen=True, kw_only=True)
class FillEvent(ForwardRecord):
    """Deterministic paper fill executed against one QuoteObservation."""

    intent_id: str
    fill_id: str | None = None
    symbol: str
    isin: str | None = None
    side: str = "BUY"
    quantity: int = 0
    price_paise: int = 0
    quote_available_at: str | None = None
    quote_provider_ts: str | None = None
    fill_status: str = FILL_FILLED
    filled_quantity: int = 0
    fee_schedule_version: str | None = None
    broker_component_version: str | None = None
    slippage_paise: int = 0
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.fill_status not in {FILL_FILLED, FILL_PARTIAL, FILL_UNFILLED,
                                    FILL_CANCELLED, FILL_EXPIRED, FILL_REJECTED,
                                    FILL_NOT_EXECUTED, FILL_NO_TRADE}:
            raise ValueError(f"unknown fill status {self.fill_status!r}")
        _check_nonneg_int(self.quantity, "quantity")
        _check_nonneg_int(self.price_paise, "price_paise")
        _check_nonneg_int(self.filled_quantity, "filled_quantity")
        _check_nonneg_int(self.slippage_paise, "slippage_paise")
        if self.fill_status in (FILL_FILLED, FILL_PARTIAL) and self.filled_quantity <= 0:
            raise ValueError("a fill requires a positive filled_quantity")
        if self.fill_status == FILL_FILLED and self.filled_quantity != self.quantity:
            raise ValueError("FILLED requires filled_quantity == quantity")
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        for name in ("quote_available_at", "quote_provider_ts"):
            value = getattr(self, name)
            if value is not None:
                _check_utc(value, name)
        if self.fill_status in (FILL_FILLED, FILL_PARTIAL) and not self.fill_id:
            raise ValueError("an executed fill requires fill_id")

    @property
    def executed_value_paise(self) -> int:
        return self.filled_quantity * self.price_paise

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "FILL_EVENT", "intent_id": self.intent_id,
                "fill_id": self.fill_id,
                "symbol": self.symbol, "isin": self.isin, "side": self.side,
                "quantity": self.quantity, "price_paise": self.price_paise,
                "quote_available_at": self.quote_available_at,
                "quote_provider_ts": self.quote_provider_ts,
                "fill_status": self.fill_status,
                "filled_quantity": self.filled_quantity,
                "executed_value_paise": self.executed_value_paise,
                "fee_schedule_version": self.fee_schedule_version,
                "broker_component_version": self.broker_component_version,
                "slippage_paise": self.slippage_paise,
                "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True, kw_only=True)
class FeeEvent(ForwardRecord):
    """Itemised integer-paise charges attributed to one fill."""

    fill_ref: str
    items: tuple[dict, ...] = ()
    total_paise: int = 0
    schedule_id: str | None = None
    broker_component: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.fill_ref:
            raise ValueError("fill_ref is required")
        _check_nonneg_int(self.total_paise, "total_paise")
        if sum(int(item.get("amount_paise", 0)) for item in self.items) != self.total_paise:
            raise ValueError("fee items must sum to total_paise")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "FEE_EVENT", "fill_ref": self.fill_ref,
                "items": [dict(item) for item in self.items],
                "total_paise": self.total_paise, "schedule_id": self.schedule_id,
                "broker_component": self.broker_component}


@dataclass(frozen=True, kw_only=True)
class CashFlow(ForwardRecord):
    """Any cash movement: fills, fees, dividends, deposits, withdrawals."""

    flow_id: str
    kind: str                                  # BUY_COST/SELL_PROCEEDS/FEE/DIVIDEND/DEPOSIT/WITHDRAWAL
    amount_paise: int = 0                      # signed: positive credits cash
    symbol: str | None = None
    isin: str | None = None
    ref: str | None = None                     # intent/fill/action reference
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.flow_id:
            raise ValueError("flow_id is required")
        if not isinstance(self.amount_paise, int) or isinstance(self.amount_paise, bool):
            raise ValueError("amount_paise must be a signed integer")
        if self.kind not in {"BUY_COST", "SELL_PROCEEDS", "SELL_PROCEEDS_NET",
                             "FEE", "DIVIDEND", "DEPOSIT", "WITHDRAWAL",
                             "ACTION_CASH"}:
            raise ValueError(f"unknown cash flow kind {self.kind!r}")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "CASH_FLOW", "flow_id": self.flow_id, "kind": self.kind,
                "amount_paise": self.amount_paise, "symbol": self.symbol,
                "isin": self.isin, "ref": self.ref,
                "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True, kw_only=True)
class CorporateActionEvent(ForwardRecord):
    """A corporate action observation affecting (or potentially affecting) the book.

    Unknown per-share/quantity value means BLOCKED: quantities and cash are never
    fabricated from a missing source.
    """

    symbol: str
    isin: str | None = None
    action_kind: str | None = None             # SPLIT/BONUS/DEMERGER/DIVIDEND/RENAME
    effective_session: str | None = None
    factor: float | None = None                # split/bonus adjustment
    dividend_per_share_paise: int | None = None
    new_symbol: str | None = None
    child_symbol: str | None = None
    child_isin: str | None = None
    child_quantity_factor: float | None = None
    child_cost_allocation_fraction: float | None = None
    status: str = "BLOCKED_UNVERIFIED_SOURCE"  # APPLIED / BLOCKED_UNVERIFIED_SOURCE / PENDING
    source_ref: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.status not in {"APPLIED", "BLOCKED_UNVERIFIED_SOURCE", "PENDING"}:
            raise ValueError(f"unknown action status {self.status!r}")
        if self.status == "APPLIED":
            if self.action_kind in ("SPLIT", "BONUS") and not self.factor:
                raise ValueError("applied split/bonus requires a verified factor")
            if self.action_kind == "DIVIDEND" and not self.dividend_per_share_paise:
                raise ValueError("applied dividend requires a verified per-share amount")
        if self.dividend_per_share_paise is not None:
            _check_nonneg_int(self.dividend_per_share_paise, "dividend_per_share_paise")
        if self.status == "APPLIED" and self.action_kind == "DEMERGER":
            if not (self.child_symbol and self.child_isin
                    and self.child_quantity_factor is not None
                    and self.child_cost_allocation_fraction is not None):
                raise ValueError("an applied demerger needs verified child identity, ratio and cost allocation")
            if self.child_quantity_factor <= 0 or not (
                    0.0 <= self.child_cost_allocation_fraction <= 1.0):
                raise ValueError("invalid demerger ratio/cost allocation")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "CORPORATE_ACTION_EVENT", "symbol": self.symbol,
                "isin": self.isin, "action_kind": self.action_kind,
                "effective_session": self.effective_session, "factor": self.factor,
                "dividend_per_share_paise": self.dividend_per_share_paise,
                "new_symbol": self.new_symbol, "status": self.status,
                "child_symbol": self.child_symbol, "child_isin": self.child_isin,
                "child_quantity_factor": self.child_quantity_factor,
                "child_cost_allocation_fraction": self.child_cost_allocation_fraction,
                "source_ref": self.source_ref,
                "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True, kw_only=True)
class ValuationMark(ForwardRecord):
    """One position mark with provenance; blocked marks never enter the NAV."""

    symbol: str
    isin: str | None = None
    quantity: int = 0
    mark_paise: int | None = None
    mark_source: str | None = None
    mark_time: str | None = None
    status: str = "MARK_OBSERVED"              # MARK_OBSERVED/MARK_BLOCKED/NO_MARK
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.status not in {"MARK_OBSERVED", "MARK_BLOCKED", "NO_MARK"}:
            raise ValueError(f"unknown mark status {self.status!r}")
        _check_nonneg_int(self.quantity, "quantity")
        if self.mark_paise is not None:
            _check_nonneg_int(self.mark_paise, "mark_paise")
        if self.status == "MARK_OBSERVED":
            if self.mark_paise is None or not self.mark_source or not self.mark_time:
                raise ValueError("an observed mark needs price, source and time")
        if self.mark_paise is None and self.status == "MARK_OBSERVED":
            raise ValueError("observed marks require mark_paise")
        if self.mark_time is not None:
            _check_utc(self.mark_time, "mark_time")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "VALUATION_MARK", "symbol": self.symbol,
                "isin": self.isin, "quantity": self.quantity,
                "mark_paise": self.mark_paise, "mark_source": self.mark_source,
                "mark_time": self.mark_time, "status": self.status,
                "blocked_reason": self.blocked_reason}


@dataclass(frozen=True, kw_only=True)
class BenchmarkMark(ForwardRecord):
    """Benchmark/control observation with explicit basis and comparability."""

    benchmark_id: str
    session_date: str | None = None
    value: float | None = None
    basis: str | None = None                   # e.g. TOTAL_RETURN_INDEX / PRICE_ONLY / CASH
    comparability: str = "COMPARABLE"          # COMPARABLE / BASIS_MISMATCH / UNAVAILABLE
    source_ref: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.benchmark_id:
            raise ValueError("benchmark_id is required")
        if self.comparability not in {"COMPARABLE", "BASIS_MISMATCH", "UNAVAILABLE"}:
            raise ValueError(f"unknown comparability {self.comparability!r}")
        if self.comparability != "UNAVAILABLE" and self.value is None:
            raise ValueError("a comparable benchmark mark needs a value")

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "BENCHMARK_MARK", "benchmark_id": self.benchmark_id,
                "session_date": self.session_date, "value": self.value,
                "basis": self.basis, "comparability": self.comparability,
                "source_ref": self.source_ref}


@dataclass(frozen=True, kw_only=True)
class RiskEvent(ForwardRecord):
    """Risk/authorization events: pauses, vetoes, limit breaches, approvals."""

    event_kind: str
    subject: str | None = None
    detail: dict = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()

    def payload(self) -> dict:
        return {**self.base_payload(),
                "record_kind": "RISK_EVENT", "event_kind": self.event_kind,
                "subject": self.subject, "detail": dict(self.detail),
                "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True, kw_only=True)
class SessionLock(ForwardRecord):
    """A locked market-session observation window for a stream."""

    session_date: str
    decision_cutoff: str
    calendar_verified: bool = False
    provider_status: str = "NOT_CONFIGURED"
    notes: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.session_date or len(self.session_date) != 10:
            raise ValueError("session_date must be an ISO date")
        _check_utc(self.decision_cutoff, "decision_cutoff")

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "SESSION_LOCK",
                "session_date": self.session_date,
                "decision_cutoff": self.decision_cutoff,
                "calendar_verified": self.calendar_verified,
                "provider_status": self.provider_status, "notes": self.notes}


@dataclass(frozen=True, kw_only=True)
class NoSignalRecord(ForwardRecord):
    """Recorded absence of a tradable decision for one candidate/day (no silent gaps)."""

    symbol: str
    candidate_id: str = "null-baseline"
    reason: str = REASON_NO_ELIGIBLE_STRATEGY
    detail: str = ""

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "NO_SIGNAL",
                "symbol": self.symbol, "candidate_id": self.candidate_id,
                "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, kw_only=True)
class AbstentionRecord(ForwardRecord):
    """An answerable candidate declined to decide (model abstained)."""

    symbol: str
    candidate_id: str = "null-baseline"
    abstention_kind: str = "MODEL_ABSTAINED"
    detail: str = ""

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "ABSTENTION",
                "symbol": self.symbol, "candidate_id": self.candidate_id,
                "abstention_kind": self.abstention_kind, "detail": self.detail}


@dataclass(frozen=True, kw_only=True)
class EligibilityFailureRecord(ForwardRecord):
    """An attempt that failed an eligibility gate, with the precise blocker."""

    symbol: str
    candidate_id: str = "null-baseline"
    stage: str = "DECISION"
    blocker: str = REASON_OPERATOR_APPROVAL_REQUIRED
    detail: str = ""

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "ELIGIBILITY_FAILURE",
                "symbol": self.symbol, "candidate_id": self.candidate_id,
                "stage": self.stage, "blocker": self.blocker, "detail": self.detail}


@dataclass(frozen=True, kw_only=True)
class ReportSnapshot(ForwardRecord):
    """An immutable, content-addressed report of a stream state."""

    report_id: str
    kind: str
    content_hash: str
    summary: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.report_id or not self.kind:
            raise ValueError("report_id and kind are required")

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "REPORT_SNAPSHOT",
                "report_id": self.report_id, "kind": self.kind,
                "content_hash": self.content_hash, "summary": dict(self.summary)}


@dataclass(frozen=True, kw_only=True)
class PreflightRecord(ForwardRecord):
    """Prospective stream preflight. It carries no market outcome or secret."""

    check_id: str
    status: str
    code_hash: str
    calendar_version: str
    rights_status: str
    fee_status: str
    action_status: str
    benchmark_status: str
    provider_status: str = "NOT_CONFIGURED"
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.check_id:
            raise ValueError("check_id is required")
        _check_sha256(self.code_hash, "code_hash")

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "PREFLIGHT",
                "check_id": self.check_id, "status": self.status,
                "code_hash": self.code_hash, "calendar_version": self.calendar_version,
                "rights_status": self.rights_status, "fee_status": self.fee_status,
                "action_status": self.action_status,
                "benchmark_status": self.benchmark_status,
                "provider_status": self.provider_status, "detail": dict(self.detail)}


@dataclass(frozen=True, kw_only=True)
class JobReceiptRecord(ForwardRecord):
    """Exactly-once worker receipt suitable for the forward hash chain."""

    receipt_id: str
    job: str
    status: str
    attempt: int = 1
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.receipt_id or not self.job or self.attempt < 1:
            raise ValueError("receipt_id/job and a positive attempt are required")

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "JOB_RECEIPT",
                "receipt_id": self.receipt_id, "job": self.job,
                "status": self.status, "attempt": self.attempt,
                "detail": dict(self.detail)}


@dataclass(frozen=True, kw_only=True)
class OutcomeObservation(ForwardRecord):
    """A matured outcome attached after a decision; never embedded in that decision."""

    decision_ref: str
    outcome_kind: str
    value: float | None = None
    observed_at: str
    source_id: str
    source_sha256: str
    status: str = "OBSERVED"

    def __post_init__(self) -> None:
        super().__post_init__()
        _check_utc(self.observed_at, "observed_at")
        _check_sha256(self.source_sha256, "source_sha256")
        if self.decision_cutoff and parse_aware_timestamp(
                self.observed_at, "observed_at") <= parse_aware_timestamp(
                    self.decision_cutoff, "decision_cutoff"):
            raise ValueError("outcome must be observed after the decision cutoff")

    def payload(self) -> dict:
        return {**self.base_payload(), "record_kind": "OUTCOME_OBSERVATION",
                "decision_ref": self.decision_ref, "outcome_kind": self.outcome_kind,
                "value": self.value, "observed_at": self.observed_at,
                "source_id": self.source_id, "source_sha256": self.source_sha256,
                "status": self.status}


RECORD_TYPES: dict[str, type] = {
    "PREFLIGHT": PreflightRecord,
    "SESSION_LOCK": SessionLock,
    "SIGNAL_DECISION": SignalDecision,
    "NO_SIGNAL": NoSignalRecord,
    "ABSTENTION": AbstentionRecord,
    "ELIGIBILITY_FAILURE": EligibilityFailureRecord,
    "PAPER_INTENT": PaperIntent,
    "QUOTE_OBSERVATION": QuoteObservation,
    "FILL_EVENT": FillEvent,
    "FEE_EVENT": FeeEvent,
    "CASH_FLOW": CashFlow,
    "CORPORATE_ACTION_EVENT": CorporateActionEvent,
    "VALUATION_MARK": ValuationMark,
    "BENCHMARK_MARK": BenchmarkMark,
    "RISK_EVENT": RiskEvent,
    "REPORT_SNAPSHOT": ReportSnapshot,
    "JOB_RECEIPT": JobReceiptRecord,
    "OUTCOME_OBSERVATION": OutcomeObservation,
}
