"""Immutable forward preregistration and the code-owned admissibility gate (W6.1).

The protocol is sealed into the stream's ledger BEFORE any observation or
decision of that stream exists.  Any post-seal change mints a completely new
stream and preserves the prior one.  Eligibility is a separate code-owned gate:
an interesting W3 gross-IC diagnostic is never proven alpha, and paper intent
requires an explicit operator approval record.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from typing import Any

from quantplus_intelligence.research_v3.wave5_common import (
    is_sha256,
    parse_aware_timestamp,
    semantic_sha256,
)

from .contracts import (
    ADMISSIBILITY_DATA_BLOCKED,
    ADMISSIBILITY_NO_ELIGIBLE_STRATEGY,
    ADMISSIBILITY_OPERATOR_APPROVAL_REQUIRED,
    ADMISSIBILITY_PAPER_ELIGIBLE,
    ADMISSIBILITY_RESEARCH_ONLY,
    MATURITY_ENGINEERING_FIXTURE,
    MATURITY_LABELS,
    MATURITY_OBSERVED_FORWARD,
)

PROTOCOL_SCHEMA = "research_v3/forward_protocol/1"

REQUIRED_RIGHTS_KEYS = ("market_data", "corporate_actions", "fee_plan", "benchmark")


@dataclass(frozen=True, kw_only=True)
class OperatorApproval:
    """A typed approval record; raw credentials or keys are never included."""

    approval_id: str
    granted_by_role: str = "operator"
    scope: str = "paper_only"                 # paper_only | observational
    granted_at: str
    note: str = ""

    def __post_init__(self) -> None:
        parse_aware_timestamp(self.granted_at, "granted_at")
        if not self.approval_id or self.scope not in ("paper_only", "observational"):
            raise ValueError("approval_id required; scope must be paper_only/observational")


@dataclass(frozen=True, kw_only=True)
class ForwardProtocol:
    """The complete frozen preregistration of one forward stream."""

    # identity
    experiment_id: str
    stream_id: str
    preregistered_at_utc: str
    preregistered_at_ist: str
    prior_version_link: str | None = None

    # strategy / model identity
    strategy_family: str | None = None
    strategy_spec_hash: str | None = None     # frozen W2 StrategySpec hash or None
    model_family: str | None = None
    model_version: str | None = None
    model_artifact_hash: str | None = None
    train_end: str | None = None
    decision_cutoff: str | None = None        # fixed evaluation cutoff, UTC
    code_commit: str | None = None
    code_hash: str | None = None
    event_ai_components: str = "OFF"          # OFF or explicit frozen version string

    # hypothesis and evaluation
    hypothesis: str = ""
    benchmarks: tuple[str, ...] = ()
    evaluation_target: str = "ABSOLUTE_NET_NAV_AND_SEPARATE_BENCHMARK_RELATIVE"
    expected_holding_period_sessions: int | None = None
    min_independent_horizons: int = 60        # preregistered sample floor, not a proof bar
    universe_rule: str | None = None
    membership_source: str | None = None
    isin_mapping_rule: str = "SAME_INSTRUMENT_BY_ISIN_ELSE_NO_TRADE"
    known_biases: tuple[str, ...] = ()
    data_availability_status: str = "PARTIAL_RETROSPECTIVE_W1_ARCHIVE"
    fee_action_rights_status: str = "FEE_PLAN_VERIFIED_2026_ACTIONS_UNVERIFIED"

    # clock and execution policy (Asia/Kolkata)
    decision_clock_ist: str | None = None
    entry_policy: str = "NEXT_ELIGIBLE_OBSERVED_QUOTE_AFTER_DECISION"
    exit_policy: str = "HORIZON_OR_STOP_OR_TARGET_WHICHEVER_FIRST"
    risk_limits: dict = field(default_factory=dict)
    max_daily_turnover_fraction: float = 1.0
    rebalance_rule: str = "NO_INTRADAY_REBALANCE"
    allowed_order_types: tuple[str, ...] = ("MARKET", "LIMIT", "STOP")
    stop_policy: str | None = None
    target_policy: str | None = None
    time_exit_sessions: int | None = None
    min_quote_max_age_seconds: int = 60
    min_observed_volume: int = 0
    max_participation_fraction: float = 0.05
    funding_model: str = "NO_MARGIN_NO_BORROW"
    cash_handling: str = "INTEGER_PAISE_LEDGER_RESERVATIONS"
    reserve_settlement_model: str = "T1_SETTLEMENT_CALENDAR_VERIFIED_SESSIONS"

    # capital and sizing
    initial_virtual_capital_paise: int | None = None
    max_position_weight: float | None = None
    max_positions: int | None = None
    operator_approval: OperatorApproval | None = None
    no_trade_conditions: tuple[str, ...] = ()
    no_leverage_policy: str = "DELIVERY_ONLY_LONG_ONLY_NO_DERIVATIVES"

    # basis and accounting
    benchmark_basis: str = "NIFTY50_TRI_IF_VERIFIABLY_AVAILABLE_ELSE_DATA_BLOCKED"
    mark_rule: str = "OBSERVED_QUOTE_OR_LAST_WITH_PROVENANCE_NEVER_DECISION_BAR"
    dividend_policy: str = "APPLY_ONLY_WITH_VERIFIED_PER_SHARE_AMOUNT_AND_EX_DATE"
    action_policy: str = "BLOCK_UNVERIFIED_QUANTITY_OR_CASH_NEVER_FABRICATE"
    broker_plan: str | None = None
    slippage_model: str = "FIXED_PAISE_TICKS_CONFIGURABLE"
    fixed_slippage_paise: int = 0
    fee_sensitivity_scenario: str = "2X_FEES_AND_SLIPPAGE_WHEN_BASE_VALID_ELSE_DATA_BLOCKED"

    # data sources and rights
    allowed_data_sources: tuple[str, ...] = ()
    source_rights: dict = field(default_factory=dict)
    provider_spend_cap_inr: float = 0.0
    notification_status: str = "WEBHOOK_NOT_CONFIGURED"

    # integrity
    content_hash: str | None = None
    ledger_head_at_seal: str | None = None

    def __post_init__(self) -> None:
        utc = parse_aware_timestamp(self.preregistered_at_utc, "preregistered_at_utc")
        ist = parse_aware_timestamp(self.preregistered_at_ist, "preregistered_at_ist")
        if utc.utcoffset() != timedelta(0):
            raise ValueError("preregistered_at_utc must be UTC")
        if ist.utcoffset() != timedelta(hours=5, minutes=30):
            raise ValueError("preregistered_at_ist must use the Asia/Kolkata +05:30 offset")
        if utc.timestamp() != ist.timestamp():
            raise ValueError("UTC and IST preregistration timestamps must name the same instant")
        if not self.experiment_id or not self.stream_id:
            raise ValueError("experiment_id and stream_id are required")
        if self.strategy_spec_hash is not None and not is_sha256(self.strategy_spec_hash):
            raise ValueError("strategy_spec_hash must be a sha256 hex digest or None")
        if self.initial_virtual_capital_paise is not None and \
                self.initial_virtual_capital_paise <= 0:
            raise ValueError("initial virtual capital must be positive paise when selected")
        if self.max_position_weight is not None and not 0 < self.max_position_weight <= 1:
            raise ValueError("max_position_weight must be in (0, 1] when selected")
        if self.max_positions is not None and self.max_positions < 1:
            raise ValueError("max_positions must be positive when selected")
        if self.fixed_slippage_paise < 0:
            raise ValueError("slippage cannot be negative")
        if self.min_independent_horizons < 1:
            raise ValueError("min_independent_horizons must be positive")
        if self.model_artifact_hash is not None and not is_sha256(self.model_artifact_hash):
            raise ValueError("model_artifact_hash must be sha256 hex or None")
        for key in REQUIRED_RIGHTS_KEYS:
            if key not in self.source_rights:
                raise ValueError(f"source_rights must declare {key!r}")
        if self.operator_approval is None and any(
                value is not None for value in (
                    self.initial_virtual_capital_paise,
                    self.max_position_weight, self.max_positions)):
            raise ValueError(
                "paper capital and sizing caps require an operator approval record")
        if self.content_hash is not None and self.content_hash != self.content_address():
            raise ValueError("content_hash does not match canonical protocol content")

    def payload(self) -> dict:
        value = asdict(self)
        value["schema"] = PROTOCOL_SCHEMA
        value["operator_approval"] = (
            asdict(self.operator_approval) if self.operator_approval else None)
        value["benchmarks"] = list(self.benchmarks)
        value["allowed_data_sources"] = list(self.allowed_data_sources)
        value["known_biases"] = list(self.known_biases)
        value["allowed_order_types"] = list(self.allowed_order_types)
        value["no_trade_conditions"] = list(self.no_trade_conditions)
        value.pop("content_hash")
        # The ledger head is produced by sealing this content and therefore is
        # seal metadata, not an input to its own content address.
        value.pop("ledger_head_at_seal")
        return value

    def content_address(self) -> str:
        return semantic_sha256(self.payload())


@dataclass(frozen=True, kw_only=True)
class StreamSeal:
    """Result of sealing a protocol: the stream identity and its first event."""

    stream_id: str
    protocol_hash: str
    sealed_at_utc: str
    sealed_at_ist: str
    event_seq: int
    event_hash: str
    is_new_stream: bool


def seal_protocol(protocol: ForwardProtocol, ledger, occurred_at: str
                  ) -> StreamSeal:
    """Idempotently seal a protocol as the stream's first ledger event.

    A different content hash under the same experiment_id mints a NEW stream_id
    (the caller must construct the new stream explicitly); sealing identical
    content twice returns the original seal.
    """
    seal_time = parse_aware_timestamp(occurred_at, "occurred_at")
    prereg_time = parse_aware_timestamp(protocol.preregistered_at_utc,
                                        "preregistered_at_utc")
    if seal_time != prereg_time:
        raise ValueError("seal event time must equal the preregistration UTC timestamp")
    content_hash = protocol.content_address()
    existing_stream = ledger.stream_records(protocol.stream_id)
    if existing_stream:
        first = existing_stream[0]
        if (len(existing_stream) == 1
                and first["event_type"] == "PREREGISTRATION_SEALED"
                and first["payload"].get("content_hash") == content_hash):
            return StreamSeal(
                stream_id=protocol.stream_id, protocol_hash=content_hash,
                sealed_at_utc=protocol.preregistered_at_utc,
                sealed_at_ist=protocol.preregistered_at_ist,
                event_seq=first["seq"], event_hash=first["record_hash"],
                is_new_stream=False)
        raise PermissionError(
            "STREAM_ALREADY_SEALED: protocol edits require a different stream_id")
    semantic_key = {"experiment_id": protocol.experiment_id,
                    "stream_id": protocol.stream_id,
                    "protocol_hash": content_hash}
    payload = {**protocol.payload(), "content_hash": content_hash,
               "ledger_head_before_seal": ledger.head()}
    record, appended = ledger.append(
        "PREREGISTRATION_SEALED", occurred_at, payload, semantic_key)
    return StreamSeal(
        stream_id=protocol.stream_id,
        protocol_hash=content_hash,
        sealed_at_utc=protocol.preregistered_at_utc,
        sealed_at_ist=protocol.preregistered_at_ist,
        event_seq=record["seq"],
        event_hash=record["record_hash"],
        is_new_stream=appended,
    )


def first_event_seq_after_seal(ledger, stream_id: str) -> int | None:
    """Seq of the first NON-preregistration event for the stream (lock sentinel)."""
    for record in ledger.stream_records(stream_id):
        if record["event_type"] != "PREREGISTRATION_SEALED":
            return record["seq"]
    return None


def stream_is_sealed_before_first_signal(ledger, stream_id: str) -> bool:
    """The preregistration event must precede every other stream event."""
    records = ledger.stream_records(stream_id)
    if not records or records[0]["event_type"] != "PREREGISTRATION_SEALED":
        return False
    return True


# --------------------------------------------------------------------------
# Admissibility gate: code-owned, evidence-driven, never a model verdict.
# --------------------------------------------------------------------------
def admissibility(protocol: ForwardProtocol, *, holdout_is_untouched: bool = False,
                   operator_approval_on_file: bool = False,
                   corporate_actions_verified: bool = False,
                   fee_plan_verified: bool = False,
                   benchmark_verified: bool = False,
                   net_returns_available: bool = False) -> dict:
    """Classify what this preregistration may do, with precise reason codes.

    The gate is deliberately conservative:
    - gross-only diagnostics (W3 rank IC) never reach PAPER_ELIGIBLE;
    - paper intent additionally requires an operator approval record on file;
    - missing fee/action/benchmark inputs keep economics DATA_BLOCKED.
    """
    reasons: list[str] = []
    has_strategy = protocol.strategy_spec_hash is not None
    has_model = protocol.model_artifact_hash is not None
    approval = protocol.operator_approval is not None and operator_approval_on_file

    integrity_ready = (corporate_actions_verified and fee_plan_verified
                       and benchmark_verified)
    if not has_strategy and not has_model:
        reasons.append("NULL_BASELINE_NO_TRADE_STREAM_BY_PREREGISTRATION")
        status = ADMISSIBILITY_NO_ELIGIBLE_STRATEGY
    elif net_returns_available and holdout_is_untouched and integrity_ready:
        if approval:
            status = ADMISSIBILITY_PAPER_ELIGIBLE
        else:
            status = ADMISSIBILITY_OPERATOR_APPROVAL_REQUIRED
            reasons.append("OPERATOR_APPROVAL_RECORD_REQUIRED_FOR_PAPER_INTENT")
    else:
        status = ADMISSIBILITY_RESEARCH_ONLY
        if not net_returns_available:
            reasons.append("NO_PROVEN_NET_ALPHA_GROSS_ONLY_DIAGNOSTIC")
        if not holdout_is_untouched:
            reasons.append("NO_NEW_UNTOUCHED_HOLDOUT_EVIDENCE")
        if has_strategy and protocol.event_ai_components != "OFF":
            reasons.append("EVENT_AI_COMPONENT_MUST_BE_OFF_OR_FROZEN")

    for key, present in (("fee_plan", fee_plan_verified),
                         ("corporate_actions", corporate_actions_verified),
                         ("benchmark", benchmark_verified)):
        if not present:
            reasons.append(f"DATA_BLOCKED_{key.upper()}")
    return {"status": status, "reasons": reasons,
            "paper_intent_allowed": status == ADMISSIBILITY_PAPER_ELIGIBLE,
            "observational_logging_allowed": True,
            "authority": "RESEARCH_ONLY"}


def require_paper_authorization(protocol: ForwardProtocol) -> None:
    """Raise unless the protocol carries an explicit paper-only operator approval."""
    approval = protocol.operator_approval
    if approval is None or approval.scope != "paper_only":
        raise PermissionError(
            "OPERATOR_APPROVAL_REQUIRED: no paper-only approval record on this stream")


def mint_new_stream(protocol: ForwardProtocol, new_stream_id: str,
                    preregistered_at_utc: str, preregistered_at_ist: str
                    ) -> ForwardProtocol:
    """Any post-seal change starts a new stream; the old one is preserved intact."""
    if not new_stream_id or new_stream_id == protocol.stream_id:
        raise ValueError("a protocol revision must mint a distinct non-empty stream_id")
    return replace(protocol, stream_id=new_stream_id,
                   preregistered_at_utc=preregistered_at_utc,
                   preregistered_at_ist=preregistered_at_ist,
                   prior_version_link=protocol.content_address(),
                   content_hash=None, ledger_head_at_seal=None)
