"""Research-namespace paper account: deterministic fills, exact paise economics.

This is a SEPARATE research account.  It never touches the V2 application book,
never calls a broker endpoint, and derives every charge from the parity-tested
``research_v3.economics`` mirror plus the date-versioned forward broker plan
(``forward.fee_sources``) — never a hard-coded cost.

Execution semantics (W6.3):
- fills happen ONLY against a QuoteObservation at the next eligible observed
  session/quote after the decision; the decision bar itself is never used;
- staleness, halt/suspension, unverified sessions, unresolved symbols, future
  timestamps, and liquidity/participation limits fail closed;
- MARKET/LIMIT/STOP, DAY expiry, partial fills and OCO linkage;
- T+1 settlement on calendar-verified sessions (unverified years fail closed
  and holdings/proceeds stay pending, never assumed settled);
- delivery-only long book: a sell requires held shares; cash never goes negative;
- corporate actions adjust quantities/cash ONLY with verified values; anything
  unverified BLOCKS the affected valuation instead of fabricating counts;
- every blocked order, no-trade day and failed valuation is recorded.
"""
from __future__ import annotations

import math
from datetime import date as date_cls, timedelta
from typing import Any

from quantplus_intelligence.exchange_calendar import is_trading_day, session_days
from quantplus_intelligence.research_v3 import economics
from quantplus_intelligence.research_v3.wave5_common import (
    parse_aware_timestamp,
    semantic_sha256,
)

from .contracts import (
    DECISION_SIGNAL,
    FILL_CANCELLED,
    FILL_EXPIRED,
    FILL_FILLED,
    FILL_NOT_EXECUTED,
    FILL_PARTIAL,
    FILL_REJECTED,
    FILL_UNFILLED,
    MATURITY_ELIGIBLE_PAPER,
    MATURITY_ENGINEERING_FIXTURE,
    INTENT_LIMIT,
    INTENT_MARKET,
    INTENT_STOP,
    REASON_ACTION_ADJUSTMENT_CANCELLED,
    REASON_ACTION_PENDING,
    REASON_CASH_SHORT,
    REASON_EXPIRED,
    REASON_FEE_SCHEDULE_UNKNOWN,
    REASON_FUTURE_QUOTE,
    REASON_INSUFFICIENT_LIQUIDITY,
    REASON_LIMIT_NOT_TOUCHED,
    REASON_OCO_CANCELLED,
    REASON_OPERATOR_APPROVAL_REQUIRED,
    REASON_SESSION_CLOSED,
    REASON_STOP_NOT_TRIGGERED,
    REASON_SYMBOL_UNRESOLVED,
    REASON_SUSPENDED,
    FillEvent,
    FeeEvent,
    CashFlow,
    CorporateActionEvent,
    PaperIntent,
    QuoteObservation,
    RiskEvent,
    ValuationMark,
)
from .fee_sources import broker_component, register_forward_plans_into_economics

register_forward_plans_into_economics()

LOT_SIZE_DEFAULT = 1

_ORDER_PENDING = "PENDING"
_ORDER_PARTIAL = "PARTIALLY_FILLED"
_ORDER_FILLED = "FILLED"


class BookError(RuntimeError):
    pass


def _ist_date_of(iso: str) -> str:
    # Storage clocks are UTC; exchange dates are always presented in IST.
    from .contracts import IST
    return parse_aware_timestamp(iso, "timestamp").astimezone(IST).date().isoformat()


def _ist_session_from(iso: str, cutoff_ist_time: str) -> str:
    """Session date an IST timestamp belongs to, given the decision clock."""
    return _ist_date_of(iso)


class _OpenOrder:
    __slots__ = ("intent", "remaining", "expiry_session", "status")

    def __init__(self, intent: PaperIntent, expiry_session: str):
        self.intent = intent
        self.remaining = intent.quantity
        self.expiry_session = expiry_session
        self.status = _ORDER_PENDING


class _Position:
    __slots__ = ("symbol", "isin", "settled_qty", "pending_buy_qty",
                 "pending_sell_qty", "cost_paise", "blocked", "blocked_reason")

    def __init__(self, symbol: str, isin: str):
        self.symbol = symbol
        self.isin = isin
        self.settled_qty = 0
        self.pending_buy_qty = 0
        self.pending_sell_qty = 0
        self.cost_paise = 0
        self.blocked = False
        self.blocked_reason: str | None = None

    @property
    def owned_qty(self) -> int:
        return self.settled_qty + self.pending_buy_qty - self.pending_sell_qty


class ResearchPaperBook:
    """Integer-paise research paper account wired to a ForwardLedger."""

    def __init__(self, ledger, stream_id: str, protocol=None, *,
                 fixture: bool = True, initial_cash_paise: int = 10_000_000,
                 lot_size: int = LOT_SIZE_DEFAULT,
                 max_participation_fraction: float | None = None,
                 fixed_slippage_paise: int | None = None):
        if not fixture:
            # This Python state machine is an independent reconciliation oracle,
            # not a second production account. Eligible paper execution must go
            # through src/lib/research-forward-paper.ts, which delegates to the
            # existing atomic TypeScript paper-book engine in a separate namespace.
            raise PermissionError(
                "AUTHORITATIVE_ENGINE_REQUIRED: non-fixture execution must use "
                "the existing paper-book adapter")
        if max_participation_fraction is None:
            max_participation_fraction = (
                protocol.max_participation_fraction if protocol
                else 0.05)
        if fixed_slippage_paise is None:
            fixed_slippage_paise = (
                protocol.fixed_slippage_paise if protocol else 0)
        self.ledger = ledger
        self.stream_id = stream_id
        self.protocol = protocol
        self.fixture = fixture
        self.lot_size = lot_size
        self.max_participation_fraction = max_participation_fraction
        self.fixed_slippage_paise = fixed_slippage_paise
        self.cash_paise = initial_cash_paise
        self.initial_cash_paise = initial_cash_paise
        self.pending_proceeds_paise = 0          # T+1 receivable from sells
        self.pending_proceeds: list[dict] = []
        self.reserved_cash_paise = 0
        self.cash_reservations: dict[str, int] = {}
        self.reserved_shares: dict[str, int] = {}
        self.share_reservations: dict[str, tuple[str, int]] = {}
        self.oco_share_reservations: dict[str, tuple[str, int]] = {}
        self.instruments: dict[str, str] = {}    # symbol -> ISIN
        self.positions: dict[str, _Position] = {}
        self.open_orders: dict[str, _OpenOrder] = {}
        self.closed_intents: dict[str, dict] = {}
        self.dp_debited: set[tuple[str, str]] = set()   # (isin, sell session)
        self._current_session: str | None = None
        self.realised_gross_paise = 0
        self.realised_net_paise = 0
        self.fees_paid_paise = 0

    # ------------------------------------------------------------ instruments
    def register_instrument(self, symbol: str, isin: str) -> None:
        if not symbol or not isin:
            raise ValueError("symbol and isin are required")
        self.instruments[symbol.upper()] = isin

    def _isin_for(self, symbol: str) -> str | None:
        return self.instruments.get(symbol.upper())

    def _position(self, isin: str, symbol: str) -> _Position:
        if isin not in self.positions:
            self.positions[isin] = _Position(symbol, isin)
        return self.positions[isin]

    # ------------------------------------------------------------ event write
    def _write(self, event_type: str, record: Any, semantic_key: dict) -> dict:
        event, _ = self.ledger.append_record(event_type, record, semantic_key)
        return event

    def _build_fee(self, side: str, turnover_paise: int, at_iso: str,
                   intent: PaperIntent, first_fill: bool,
                   fill_ref: str) -> tuple[FeeEvent, tuple[str, str] | None]:
        """Itemised charges via the parity-tested mirror + verified DP plan.

        The ``economics`` mirror carries the zero/„per-order brokerage” broker
        components; the FYERS per-scrip DP debit is added here once per
        (ISIN, sell session) so it stays separately auditable.
        """
        plan = (self.protocol.broker_plan if self.protocol
                and self.protocol.broker_plan else "book_zero_brokerage")
        try:
            charges = economics.delivery_charges(
                side, turnover_paise, at_iso, broker=plan,
                first_fill_of_order=first_fill)
        except ValueError as exc:
            raise BookError(f"{REASON_FEE_SCHEDULE_UNKNOWN}: {exc}") from exc
        items = [dict(item) for item in charges["items"]]
        total = charges["total_paise"]
        # DP debit: once per ISIN per sell day, only for a sell's first fill.
        dp_key: tuple[str, str] | None = None
        if side == "SELL" and first_fill:
            component = broker_component(plan, at_iso)          # fail-closed
            session = _ist_date_of(at_iso)
            isin = intent.isin or self._isin_for(intent.symbol) or intent.symbol
            if component.get("dp_debit_paise") and (isin, session) not in self.dp_debited:
                dp_amount = component["dp_debit_paise"]
                gst = economics._apply_rate(dp_amount, component["dp_gst_rate"])
                dp_key = (isin, session)
                items.append({"code": "DP", "amount_paise": dp_amount,
                              "basis": component.get("dp_basis",
                                                     "per-scrip sell-side DP debit")})
                items.append({"code": "DP_GST", "amount_paise": gst,
                              "basis": "18% GST on the DP debit"})
                total += dp_amount + gst
        record = FeeEvent(stream_id=self.stream_id,
                          recorded_at=at_iso,
                          maturity=self._maturity(),
                          fill_ref=fill_ref,
                          items=tuple(items),
                          total_paise=total,
                          schedule_id=charges["schedule"],
                          broker_component=charges["broker_component"])
        return record, dp_key

    def _record_fee(self, record: FeeEvent, *, side: str, turnover_paise: int,
                    at_iso: str, first_fill: bool,
                    dp_key: tuple[str, str] | None) -> None:
        self._write("FEE_EVENT", record, {
            "stream": self.stream_id, "fill": record.fill_ref, "side": side,
            "turnover": turnover_paise, "at": at_iso, "first": first_fill})
        if dp_key is not None:
            self.dp_debited.add(dp_key)
        self.fees_paid_paise += record.total_paise

    def _maturity(self) -> str:
        if self.fixture:
            return MATURITY_ENGINEERING_FIXTURE
        return MATURITY_ELIGIBLE_PAPER

    # -------------------------------------------------------------- submitting
    def submit_intent(self, intent: PaperIntent) -> dict:
        """Validate and record a paper intent; returns the acceptance outcome."""
        if intent.intent_id in self.open_orders or intent.intent_id in self.closed_intents:
            raise BookError(f"duplicate intent {intent.intent_id}")
        isin = intent.isin or self._isin_for(intent.symbol)
        reasons: list[str] = []
        if isin is None:
            return self._reject(intent, FILL_REJECTED, [REASON_SYMBOL_UNRESOLVED])
        if not self.fixture and not intent.approved_for_paper:
            return self._reject(intent, FILL_REJECTED,
                                [REASON_OPERATOR_APPROVAL_REQUIRED])
        if intent.quantity is None:
            return self._reject(intent, FILL_REJECTED, ["QUANTITY_REQUIRED"])
        if intent.quantity % self.lot_size != 0:
            return self._reject(intent, FILL_REJECTED,
                                ["QUANTITY_NOT_MULTIPLE_OF_LOT"])
        if intent.decision is not None and intent.decision.decision != DECISION_SIGNAL:
            return self._reject(intent, FILL_REJECTED, ["INTENT_WITHOUT_SIGNAL"])
        session = intent.session_date or _ist_date_of(intent.recorded_at)
        if is_trading_day(date_cls.fromisoformat(session)) is not True:
            return self._reject(intent, FILL_NOT_EXECUTED, [REASON_SESSION_CLOSED])
        # Worst-case affordability before acceptance (cash never goes negative).
        if intent.side == "BUY":
            worst_price = (intent.limit_paise if intent.order_type == INTENT_LIMIT
                           else None)
            if worst_price is None:
                worst_price = 10 ** 9  # unknown until quote; re-checked at fill
            est_cost = intent.quantity * worst_price
            est_charges = self._estimate_charges("BUY", est_cost, session) \
                if intent.order_type == INTENT_LIMIT else None
            if intent.order_type == INTENT_LIMIT and \
                    est_cost + est_charges["total_paise"] > self.cash_paise:
                return self._reject(intent, FILL_NOT_EXECUTED, [REASON_CASH_SHORT])
            reserve = (est_cost + est_charges["total_paise"]
                       if intent.order_type == INTENT_LIMIT
                       else intent.notional_paise)
            if reserve is None or reserve <= 0:
                return self._reject(intent, FILL_NOT_EXECUTED,
                                    ["MARKET_BUY_NOTIONAL_RESERVATION_REQUIRED"])
            if reserve > self.cash_paise - self.reserved_cash_paise:
                return self._reject(intent, FILL_NOT_EXECUTED, [REASON_CASH_SHORT])
            self.reserved_cash_paise += reserve
            self.cash_reservations[intent.intent_id] = reserve
        else:
            held = self._sellable(isin)
            existing_group = (self.oco_share_reservations.get(intent.oco_group)
                              if intent.oco_group else None)
            if existing_group is not None:
                if existing_group[0] != isin or intent.quantity > existing_group[1]:
                    return self._reject(intent, FILL_NOT_EXECUTED, [REASON_CASH_SHORT])
                self.share_reservations[intent.intent_id] = (isin, 0)
            else:
                if held < intent.quantity:
                    return self._reject(intent, FILL_NOT_EXECUTED, [REASON_CASH_SHORT])
                self.reserved_shares[isin] = self.reserved_shares.get(isin, 0) + intent.quantity
                self.share_reservations[intent.intent_id] = (isin, intent.quantity)
                if intent.oco_group:
                    self.oco_share_reservations[intent.oco_group] = (isin, intent.quantity)
        expiry = self._expiry_session(session, intent.time_in_force_sessions)
        self.open_orders[intent.intent_id] = _OpenOrder(intent, expiry)
        self._write("PAPER_INTENT", intent, {
            "stream": self.stream_id, "intent": intent.intent_id})
        return {"intent_id": intent.intent_id, "accepted": True,
                "isin": isin, "expiry_session": expiry, "status": _ORDER_PENDING}

    def _estimate_charges(self, side: str, turnover: int, session: str) -> dict:
        at_iso = f"{session}T10:00:00+00:00"
        return economics.delivery_charges(side, turnover, at_iso,
                                          broker=(self.protocol.broker_plan
                                                  if self.protocol and self.protocol.broker_plan
                                                  else "book_zero_brokerage"))

    def _expiry_session(self, start_session: str, tif_sessions: int) -> str:
        """Last session an order may trade on (DAY = its acceptance session)."""
        day = date_cls.fromisoformat(start_session)
        horizon = max(1, tif_sessions)
        sessions = session_days(date_cls.fromisoformat(start_session),
                                day + timedelta(days=60))
        if sessions:
            eligible = [s for s in sessions if s >= start_session]
            if eligible:
                return eligible[min(horizon - 1, len(eligible) - 1)]
        return start_session

    def _reject(self, intent: PaperIntent, status: str, reasons: list[str]) -> dict:
        record = FillEvent(stream_id=self.stream_id,
                           recorded_at=intent.recorded_at,
                           maturity=self._maturity(),
                           intent_id=intent.intent_id,
                           symbol=intent.symbol, isin=intent.isin,
                           side=intent.side, quantity=intent.quantity or 0,
                           price_paise=0,
                           fill_status=status, filled_quantity=0,
                           reason_codes=tuple(reasons))
        self._write("FILL_EVENT", record, {
            "stream": self.stream_id, "intent": intent.intent_id,
            "status": status, "reasons": sorted(reasons)})
        self._release_reservation(intent.intent_id)
        self.closed_intents[intent.intent_id] = record.payload()
        return {"intent_id": intent.intent_id, "accepted": False,
                "status": status, "reasons": reasons}

    # ---------------------------------------------------------- quote pipeline
    def _sellable(self, isin: str) -> int:
        pos = self.positions.get(isin)
        # Delivery-only exits use settled shares. Pending T+1 buys are not
        # silently converted into an intraday sell.
        return ((pos.settled_qty - pos.pending_sell_qty
                 - self.reserved_shares.get(isin, 0)) if pos else 0)

    def observe_quote(self, quote: QuoteObservation) -> list[dict]:
        """Run every eligible open order against one observed quote."""
        _, appended = self.ledger.append_record("QUOTE_OBSERVATION", quote, {
            "stream": self.stream_id, "symbol": quote.symbol,
            "provider": quote.provider, "provider_ts": quote.provider_ts,
            "available_at": quote.available_at, "session": quote.session_date})
        if not appended:
            # A duplicate trigger is a replay, not another fill opportunity.
            return []
        self._current_session = quote.session_date or _ist_date_of(quote.recorded_at)
        session = self._current_session
        self._expire_orders(session, quote.recorded_at)
        outcomes: list[dict] = []
        for order in list(self.open_orders.values()):
            if order.intent.symbol.upper() != quote.symbol.upper():
                continue
            if order.status == _ORDER_FILLED:
                continue
            outcome = self._evaluate(order, quote)
            if outcome:
                outcomes.append(outcome)
            if order.status == _ORDER_FILLED:
                self._settle_oco(order.intent, quote.recorded_at)
        return outcomes

    def _expire_orders(self, session: str, at_iso: str) -> None:
        for order_id, order in list(self.open_orders.items()):
            if order.expiry_session < session:
                reasons = ([REASON_STOP_NOT_TRIGGERED]
                           if order.intent.order_type == INTENT_STOP else
                           ([REASON_LIMIT_NOT_TOUCHED]
                            if order.intent.order_type == INTENT_LIMIT else
                            [])) or [REASON_EXPIRED]
                self._record_terminal(order, FILL_EXPIRED,
                                       order.remaining,
                                       0, reasons, at_iso=at_iso)
                del self.open_orders[order_id]

    def _evaluate(self, order: _OpenOrder, quote: QuoteObservation) -> dict | None:
        intent = order.intent
        reasons: list[str] = []
        # ---- fail-closed quote gates -------------------------------------
        quote_session = quote.session_date or _ist_date_of(quote.recorded_at)
        if is_trading_day(date_cls.fromisoformat(quote_session)) is not True:
            reasons.append(REASON_SESSION_CLOSED)
        if quote.symbol.upper() != intent.symbol.upper():
            reasons.append(REASON_SYMBOL_UNRESOLVED)
        intended_isin = intent.isin or self._isin_for(intent.symbol)
        if quote.isin and intended_isin and quote.isin != intended_isin:
            reasons.append(REASON_SYMBOL_UNRESOLVED)
        if quote.stale:
            reasons.append("QUOTE_STALE")
        if quote.halted_or_suspended:
            reasons.append(REASON_SUSPENDED)
        if quote.provider_ts is not None and quote.recorded_at is not None and \
                parse_aware_timestamp(quote.provider_ts, "provider_ts") > \
                parse_aware_timestamp(quote.recorded_at, "recorded_at"):
            reasons.append(REASON_FUTURE_QUOTE)
        if quote.available_at is None:
            reasons.append("QUOTE_AVAILABLE_AT_MISSING")
        else:
            available = parse_aware_timestamp(quote.available_at, "available_at")
            recorded = parse_aware_timestamp(quote.recorded_at, "recorded_at")
            if available > recorded:
                reasons.append(REASON_FUTURE_QUOTE)
            if intent.decision is not None and intent.decision.decision_cutoff:
                cutoff = parse_aware_timestamp(intent.decision.decision_cutoff,
                                               "decision_cutoff")
                if available <= cutoff:
                    reasons.append("QUOTE_NOT_AFTER_DECISION")
        if quote.provider_ts:
            provider_ts = parse_aware_timestamp(quote.provider_ts, "provider_ts")
            recorded = parse_aware_timestamp(quote.recorded_at, "recorded_at")
            max_age = (self.protocol.min_quote_max_age_seconds
                       if self.protocol else 60)
            if (recorded - provider_ts).total_seconds() > max_age:
                reasons.append("QUOTE_STALE")
        if self.protocol and quote.provider not in self.protocol.allowed_data_sources:
            reasons.append("QUOTE_PROVIDER_NOT_ALLOWLISTED")
        if reasons:
            return self._not_executed(order, sorted(set(reasons)), quote.recorded_at)
        price = quote.executable_price_paise(intent.side, self.fixed_slippage_paise)
        if price is None:
            return self._not_executed(order, [REASON_SUSPENDED, "NO_EXECUTABLE_PRICE"],
                                      quote.recorded_at)
        if intent.order_type == INTENT_LIMIT:
            if intent.limit_paise is None:
                return self._not_executed(order, ["LIMIT_PRICE_REQUIRED"], quote.recorded_at)
            if (intent.side == "BUY" and price > intent.limit_paise) or \
                    (intent.side == "SELL" and price < intent.limit_paise):
                return self._not_executed(order, [REASON_LIMIT_NOT_TOUCHED], quote.recorded_at)
        elif intent.order_type == INTENT_STOP:
            if intent.stop_paise is None:
                return self._not_executed(order, ["STOP_PRICE_REQUIRED"], quote.recorded_at)
            ref = (quote.ask_paise or quote.last_paise) if intent.side == "BUY" \
                else (quote.bid_paise or quote.last_paise)
            if ref is None:
                return self._not_executed(order, ["NO_TRIGGER_REFERENCE"], quote.recorded_at)
            if (intent.side == "BUY" and ref < intent.stop_paise) or \
                    (intent.side == "SELL" and ref > intent.stop_paise):
                return None  # not triggered yet; keep waiting (no record spam)
        # ---- liquidity / participation ------------------------------------
        requested = order.remaining
        volume = quote.volume
        if volume is not None and volume <= 0:
            return self._not_executed(order, [REASON_INSUFFICIENT_LIQUIDITY],
                                      quote.recorded_at)
        cap = requested
        if volume is not None:
            cap = min(cap, int(volume * self.max_participation_fraction))
        if quote.depth_lots is not None:
            cap = min(cap, quote.depth_lots * self.lot_size)
        cap -= (cap % self.lot_size)
        fill_qty = min(requested, cap)
        if fill_qty <= 0:
            return self._not_executed(order, [REASON_INSUFFICIENT_LIQUIDITY],
                                      quote.recorded_at)
        return self._execute_fill(order, quote, price, fill_qty,
                                  partial=fill_qty < requested)

    def _not_executed(self, order: _OpenOrder, reasons: list[str],
                      at_iso: str | None = None) -> dict:
        """A blocked/no-trade evaluation is RECORDED, but the order stays open
        (only DAY expiry or explicit cancellation closes it)."""
        record = FillEvent(stream_id=self.stream_id,
                           recorded_at=at_iso or order.intent.recorded_at,
                           maturity=self._maturity(),
                           intent_id=order.intent.intent_id,
                           symbol=order.intent.symbol,
                           isin=order.intent.isin or self._isin_for(order.intent.symbol),
                           side=order.intent.side,
                           quantity=order.remaining, price_paise=0,
                           fill_status=FILL_NOT_EXECUTED, filled_quantity=0,
                           slippage_paise=self.fixed_slippage_paise,
                           reason_codes=tuple(reasons))
        self._write("FILL_EVENT", record, {
            "stream": self.stream_id, "intent": order.intent.intent_id,
            "status": FILL_NOT_EXECUTED, "reasons": sorted(reasons),
            "at": at_iso or order.intent.recorded_at})
        return {"intent_id": order.intent.intent_id,
                "status": FILL_NOT_EXECUTED, "reasons": reasons}

    def _execute_fill(self, order: _OpenOrder, quote: QuoteObservation,
                      price: int, fill_qty: int, *, partial: bool) -> dict:
        intent = order.intent
        isin = intent.isin or self._isin_for(intent.symbol) or intent.symbol
        session = quote.session_date or _ist_date_of(quote.recorded_at)
        recorded_at = quote.recorded_at
        turnover = fill_qty * price
        first_fill = order.status == _ORDER_PENDING
        status = FILL_PARTIAL if partial else FILL_FILLED
        reasons: list[str] = []
        fill_id = semantic_sha256({
            "stream": self.stream_id, "intent": intent.intent_id,
            "quote": quote.payload(), "fill_number":
                sum(1 for event in self.ledger.stream_records(self.stream_id, "FILL_EVENT")
                    if event["payload"].get("intent_id") == intent.intent_id
                    and event["payload"].get("fill_status") in (FILL_FILLED, FILL_PARTIAL)),
            "quantity": fill_qty, "price_paise": price,
        })
        fee, dp_key = self._build_fee(intent.side, turnover, recorded_at, intent,
                                      first_fill, fill_id)
        # ---- cash / share checks ------------------------------------------
        if intent.side == "BUY":
            cost = turnover + fee.total_paise
            own_reserve = self.cash_reservations.get(intent.intent_id, 0)
            available_for_order = self.cash_paise - self.reserved_cash_paise + own_reserve
            if cost > available_for_order:
                return self._not_executed(order, [REASON_CASH_SHORT], recorded_at)
            self.cash_paise -= cost
            self._consume_cash_reservation(intent.intent_id, cost)
            self._cashflow("BUY_COST", -turnover, intent, isin, recorded_at,
                           fill_ref=fill_id)
            self._cashflow("FEE", -fee.total_paise, intent, isin, recorded_at,
                           fill_ref=fill_id)
            pos = self._position(isin, quote.symbol)
            pos.pending_buy_qty += fill_qty
            pos.cost_paise += turnover
        else:
            pos = self.positions.get(isin)
            own_reserved = self.share_reservations.get(intent.intent_id, (isin, 0))[1]
            if intent.oco_group and intent.oco_group in self.oco_share_reservations:
                own_reserved = self.oco_share_reservations[intent.oco_group][1]
            other_reserved = self.reserved_shares.get(isin, 0) - own_reserved
            if pos is None or pos.settled_qty - other_reserved < fill_qty:
                return self._not_executed(order, [REASON_CASH_SHORT], recorded_at)
            before_qty = pos.owned_qty
            allocated_cost = (pos.cost_paise if fill_qty == before_qty else
                              round(pos.cost_paise * fill_qty / before_qty))
            pos.settled_qty -= fill_qty
            pos.cost_paise -= allocated_cost
            self._consume_share_reservation(intent.intent_id, fill_qty)
            net = turnover - fee.total_paise
            due = self._next_session(session)
            self.pending_proceeds.append({"trade_session": session,
                                          "due_session": due,
                                          "amount_paise": net,
                                          "fill_id": fill_id})
            self.pending_proceeds_paise += net
            self._cashflow("SELL_PROCEEDS", turnover, intent, isin, recorded_at,
                           pending=True, fill_ref=fill_id)
            self._cashflow("FEE", -fee.total_paise, intent, isin, recorded_at,
                           pending=True, fill_ref=fill_id)
            gross = turnover - allocated_cost
            self.realised_gross_paise += gross
            self.realised_net_paise += gross - fee.total_paise
        fill = FillEvent(stream_id=self.stream_id,
                         recorded_at=recorded_at,
                         maturity=self._maturity(),
                         session_date=session,
                         intent_id=intent.intent_id,
                         fill_id=fill_id,
                         symbol=quote.symbol, isin=isin,
                         side=intent.side, quantity=order.remaining,
                         price_paise=price,
                         quote_available_at=quote.available_at,
                         quote_provider_ts=quote.provider_ts,
                         fill_status=status,
                         filled_quantity=fill_qty,
                         fee_schedule_version=fee.schedule_id,
                         broker_component_version=fee.broker_component,
                         slippage_paise=self.fixed_slippage_paise,
                         reason_codes=tuple(reasons))
        self._write("FILL_EVENT", fill, {
            "stream": self.stream_id, "intent": intent.intent_id,
            "status": status, "qty": fill_qty, "price": price,
            "at": recorded_at})
        self._record_fee(fee, side=intent.side, turnover_paise=turnover,
                         at_iso=recorded_at, first_fill=first_fill, dp_key=dp_key)
        order.remaining -= fill_qty
        order.status = _ORDER_FILLED if order.remaining == 0 else _ORDER_PARTIAL
        if order.remaining == 0:
            self._release_reservation(intent.intent_id)
            del self.open_orders[intent.intent_id]
        elif intent.order_type == INTENT_MARKET:
            # Match the established engine: a market order is IOC against the
            # observed top of book; its liquidity-limited remainder is cancelled.
            remainder = order.remaining
            self._record_terminal(order, FILL_CANCELLED, remainder, 0,
                                  [REASON_INSUFFICIENT_LIQUIDITY], at_iso=recorded_at)
            self._release_reservation(intent.intent_id)
            del self.open_orders[intent.intent_id]
        return {"intent_id": intent.intent_id, "status": status,
                "filled_quantity": fill_qty, "price_paise": price,
                "fees_paise": fee.total_paise}

    def _cashflow(self, kind: str, amount: int, intent: PaperIntent,
                  isin: str, at_iso: str, *, pending: bool = False,
                  fill_ref: str | None = None) -> None:
        # The flow id embeds the fill timestamp so multiple partial fills of one
        # intent never collide on the exactly-once semantic key.
        record = CashFlow(stream_id=self.stream_id,
                          recorded_at=at_iso,
                          maturity=self._maturity(),
                          session_date=_ist_date_of(at_iso),
                          flow_id=f"{intent.intent_id}:{fill_ref or at_iso}:{kind}",
                          kind=kind,
                          amount_paise=amount,
                          symbol=intent.symbol, isin=isin,
                          ref=fill_ref or intent.intent_id)
        self._write("CASH_FLOW", record, {
            "stream": self.stream_id, "flow": record.flow_id})

    def _consume_cash_reservation(self, intent_id: str, amount: int) -> None:
        reserved = self.cash_reservations.get(intent_id, 0)
        consumed = min(reserved, amount)
        remaining = reserved - consumed
        self.reserved_cash_paise -= consumed
        if remaining:
            self.cash_reservations[intent_id] = remaining
        else:
            self.cash_reservations.pop(intent_id, None)

    def _consume_share_reservation(self, intent_id: str, quantity: int) -> None:
        item = self.share_reservations.get(intent_id)
        if item is None:
            return
        isin, reserved = item
        order = self.open_orders.get(intent_id)
        group = order.intent.oco_group if order else None
        if group and group in self.oco_share_reservations:
            isin, reserved = self.oco_share_reservations[group]
            consumed = min(quantity, reserved)
            self.reserved_shares[isin] = max(
                0, self.reserved_shares.get(isin, 0) - consumed)
            remaining = reserved - consumed
            if remaining:
                self.oco_share_reservations[group] = (isin, remaining)
            else:
                self.oco_share_reservations.pop(group, None)
            return
        consumed = min(quantity, reserved)
        self.reserved_shares[isin] = max(0, self.reserved_shares.get(isin, 0) - consumed)
        remaining = reserved - consumed
        if remaining:
            self.share_reservations[intent_id] = (isin, remaining)
        else:
            self.share_reservations.pop(intent_id, None)

    def _release_reservation(self, intent_id: str) -> None:
        cash = self.cash_reservations.pop(intent_id, 0)
        self.reserved_cash_paise = max(0, self.reserved_cash_paise - cash)
        shares = self.share_reservations.pop(intent_id, None)
        if shares:
            isin, quantity = shares
            order = self.open_orders.get(intent_id)
            group = order.intent.oco_group if order else None
            if group and group in self.oco_share_reservations:
                group_isin, group_quantity = self.oco_share_reservations.pop(group)
                self.reserved_shares[group_isin] = max(
                    0, self.reserved_shares.get(group_isin, 0) - group_quantity)
            elif quantity:
                self.reserved_shares[isin] = max(
                    0, self.reserved_shares.get(isin, 0) - quantity)

    def _next_session(self, session: str) -> str | None:
        day = date_cls.fromisoformat(session)
        sessions = [s for s in session_days(day + timedelta(days=1),
                                            day + timedelta(days=20))]
        return sessions[0] if sessions else None

    def _record_terminal(self, order: _OpenOrder, status: str, quantity: int,
                         filled: int, reasons: list[str], *,
                         at_iso: str | None = None) -> None:
        intent = order.intent
        record = FillEvent(stream_id=self.stream_id,
                           recorded_at=at_iso or intent.recorded_at,
                           maturity=self._maturity(),
                           intent_id=intent.intent_id,
                           symbol=intent.symbol,
                           isin=intent.isin or self._isin_for(intent.symbol),
                           side=intent.side, quantity=quantity,
                           price_paise=0,
                           fill_status=status,
                           filled_quantity=filled,
                           reason_codes=tuple(reasons))
        self._write("FILL_EVENT", record, {
            "stream": self.stream_id, "intent": intent.intent_id,
            "status": status, "reasons": sorted(reasons)})
        self.closed_intents[intent.intent_id] = record.payload()

    # ---------------------------------------------------------------- OCO ----
    def _settle_oco(self, filled_intent: PaperIntent, at_iso: str) -> None:
        group = filled_intent.oco_group
        if not group:
            return
        for order in list(self.open_orders.values()):
            if order.intent.oco_group == group and \
                    order.intent.intent_id != filled_intent.intent_id:
                self._record_terminal(order, FILL_CANCELLED, order.remaining, 0,
                                      [REASON_OCO_CANCELLED], at_iso=at_iso)
                del self.open_orders[order.intent.intent_id]

    def cancel_intent(self, intent_id: str, reason: str,
                      at_iso: str) -> dict | None:
        order = self.open_orders.get(intent_id)
        if order is None:
            return None
        self._record_terminal(order, FILL_CANCELLED, order.remaining, 0, [reason],
                              at_iso=at_iso)
        del self.open_orders[intent_id]
        return {"intent_id": intent_id, "cancelled": True}

    # ----------------------------------------------------------- settlement ---
    def settle(self, session_date: str) -> dict:
        """T+1 settlement on a calendar-verified session (fail-closed, durable).

        Idempotent: a SETTLEMENT_COMPLETED risk event in the stream ledger
        guards against re-running a session after a crash or restart.
        """
        verdict = is_trading_day(date_cls.fromisoformat(session_date))
        if verdict is not True:
            return {"session_date": session_date, "settled": False,
                    "reason": REASON_SESSION_CLOSED}
        for event in self.ledger.stream_records(self.stream_id, "RISK_EVENT"):
            payload = event["payload"]
            if payload.get("event_kind") == "SETTLEMENT_COMPLETED" and \
                    payload.get("detail", {}).get("session_date") == session_date:
                return {"session_date": session_date, "settled": True,
                        "already_settled": True}
        # Fills from the previous trading session become settled today.
        previous = self._previous_session(session_date)
        moved_buys = moved_sells = 0
        if previous is None:
            return {"session_date": session_date, "settled": True,
                    "note": "no verified prior session; nothing to settle"}
        for event in self.ledger.stream_records(self.stream_id, "FILL_EVENT"):
            payload = event["payload"]
            if payload.get("session_date") != previous:
                continue
            if payload["fill_status"] not in (FILL_FILLED, FILL_PARTIAL):
                continue
            isin = payload.get("isin") or payload["symbol"]
            pos = self._position(isin, payload["symbol"])
            qty = payload["filled_quantity"]
            if payload["side"] == "BUY":
                pos.pending_buy_qty -= qty
                pos.settled_qty += qty
                moved_buys += qty
            else:
                moved_sells += qty
        due_rows = [row for row in self.pending_proceeds
                    if row.get("due_session") is not None
                    and row["due_session"] <= session_date]
        credited = sum(row["amount_paise"] for row in due_rows)
        self.cash_paise += credited
        self.pending_proceeds = [row for row in self.pending_proceeds
                                 if row not in due_rows]
        self.pending_proceeds_paise -= credited
        settlement_event = RiskEvent(
            stream_id=self.stream_id, recorded_at=f"{session_date}T10:00:00+00:00",
            maturity=self._maturity(), event_kind="SETTLEMENT_COMPLETED",
            subject=session_date,
            detail={"session_date": session_date, "previous_session": previous,
                    "shares_settled_buy": moved_buys,
                    "shares_settled_sell": moved_sells,
                    "proceeds_credited_paise": credited})
        self._write("RISK_EVENT", settlement_event, {
            "stream": self.stream_id, "kind": "SETTLEMENT_COMPLETED",
            "session": session_date})
        return {"session_date": session_date, "settled": True,
                "previous_session": previous,
                "shares_settled_buy": moved_buys,
                "shares_settled_sell": moved_sells,
                "proceeds_credited_paise": credited}

    def _previous_session(self, session_date: str) -> str | None:
        day = date_cls.fromisoformat(session_date)
        back = day - timedelta(days=1)
        window = session_days(day - timedelta(days=30), day)
        prior = [s for s in window if s < session_date]
        if not prior:
            return None
        # The immediately preceding trading session that had fills is the one
        # settling today; simplified to the last calendar session.
        return prior[-1]

    # --------------------------------------------------- corporate actions ---
    def apply_corporate_action(self, event: CorporateActionEvent) -> dict:
        """Apply only verified values; anything else BLOCKS the position."""
        isin = event.isin or self._isin_for(event.symbol)
        if isin is None:
            return {"applied": False, "reason": REASON_SYMBOL_UNRESOLVED}
        self._write("CORPORATE_ACTION_EVENT", event, {
            "stream": self.stream_id, "action": event.symbol,
            "kind": event.action_kind, "session": event.effective_session,
            "status": event.status, "recorded_at": event.recorded_at})
        if event.status != "APPLIED":
            pos = self._position(isin, event.symbol)
            pos.blocked = True
            pos.blocked_reason = REASON_ACTION_PENDING
            return {"applied": False,
                    "reason": REASON_ACTION_PENDING,
                    "position_blocked": True}
        if event.action_kind in ("SPLIT", "BONUS"):
            factor = event.factor
            if not factor or factor <= 0:
                return {"applied": False, "reason": "MISSING_VERIFIED_FACTOR"}
            pos = self._position(isin, event.symbol)
            quantities = (pos.settled_qty * factor,
                          pos.pending_buy_qty * factor,
                          pos.pending_sell_qty * factor)
            if any(not float(value).is_integer() for value in quantities):
                pos.blocked = True
                pos.blocked_reason = "FRACTIONAL_ACTION_ENTITLEMENT_UNVERIFIED"
                return {"applied": False,
                        "reason": "FRACTIONAL_ACTION_ENTITLEMENT_UNVERIFIED",
                        "position_blocked": True}
            new_total = int(quantities[0])
            pos.settled_qty = new_total
            pos.pending_buy_qty = int(quantities[1])
            pos.pending_sell_qty = int(quantities[2])
            for order in list(self.open_orders.values()):
                if order.intent.isin == isin or \
                        order.intent.symbol.upper() == event.symbol.upper():
                    self._record_terminal(
                        order, FILL_CANCELLED, order.remaining, 0,
                        [REASON_ACTION_ADJUSTMENT_CANCELLED],
                        at_iso=event.recorded_at)
                    del self.open_orders[order.intent.intent_id]
            return {"applied": True, "kind": event.action_kind,
                    "new_qty": pos.owned_qty}
        if event.action_kind == "DIVIDEND":
            if not event.dividend_per_share_paise:
                return {"applied": False, "reason": "MISSING_VERIFIED_DIVIDEND"}
            pos = self._position(isin, event.symbol)
            qty = pos.settled_qty
            if qty <= 0:
                return {"applied": False, "reason": "NO_HOLDING_ON_EX_DATE"}
            credit = qty * event.dividend_per_share_paise
            self.cash_paise += credit
            record = CashFlow(stream_id=self.stream_id,
                              recorded_at=event.recorded_at,
                              maturity=self._maturity(),
                              session_date=event.effective_session,
                              flow_id=f"DIV:{event.symbol}:{event.effective_session}",
                              kind="DIVIDEND",
                              amount_paise=credit,
                              symbol=event.symbol, isin=isin,
                              ref=event.payload()["record_kind"])
            self._write("CASH_FLOW", record, {
                "stream": self.stream_id, "flow": record.flow_id})
            return {"applied": True, "kind": "DIVIDEND", "credit_paise": credit,
                    "quantity": qty}
        if event.action_kind == "RENAME":
            if not event.new_symbol:
                return {"applied": False, "reason": "MISSING_NEW_SYMBOL"}
            self.instruments.pop(event.symbol.upper(), None)
            self.instruments[event.new_symbol.upper()] = isin
            pos = self._position(isin, event.symbol)
            pos.symbol = event.new_symbol
            return {"applied": True, "kind": "RENAME",
                    "isin_preserved": isin}
        if event.action_kind == "DEMERGER":
            pos = self._position(isin, event.symbol)
            if not (event.child_symbol and event.child_isin
                    and event.child_quantity_factor is not None
                    and event.child_cost_allocation_fraction is not None):
                pos.blocked = True
                pos.blocked_reason = "DEMERGER_VALUE_UNVERIFIED"
                return {"applied": False, "reason": "DEMERGER_VALUE_UNVERIFIED",
                        "position_blocked": True}
            child_qty_raw = pos.settled_qty * event.child_quantity_factor
            if not float(child_qty_raw).is_integer():
                pos.blocked = True
                pos.blocked_reason = "FRACTIONAL_DEMERGER_ENTITLEMENT_UNVERIFIED"
                return {"applied": False,
                        "reason": "FRACTIONAL_DEMERGER_ENTITLEMENT_UNVERIFIED",
                        "position_blocked": True}
            child = self._position(event.child_isin, event.child_symbol)
            child.settled_qty += int(child_qty_raw)
            child_cost = round(pos.cost_paise * event.child_cost_allocation_fraction)
            child.cost_paise += child_cost
            pos.cost_paise -= child_cost
            self.instruments[event.child_symbol.upper()] = event.child_isin
            return {"applied": True, "kind": "DEMERGER",
                    "child_symbol": event.child_symbol,
                    "child_isin": event.child_isin,
                    "child_quantity": int(child_qty_raw),
                    "child_cost_paise": child_cost}
        return {"applied": False, "reason": "ACTION_KIND_UNSUPPORTED"}

    # ---------------------------------------------------------------- NAV ----
    def mark_position(self, mark: ValuationMark) -> dict:
        isin = mark.isin or self._isin_for(mark.symbol)
        if isin is None:
            return {"marked": False, "reason": REASON_SYMBOL_UNRESOLVED}
        self._write("VALUATION_MARK", mark, {
            "stream": self.stream_id, "mark": mark.symbol,
            "session": mark.session_date or _ist_date_of(mark.recorded_at)})
        if mark.status == "MARK_BLOCKED":
            pos = self._position(isin, mark.symbol)
            pos.blocked = True
            pos.blocked_reason = mark.blocked_reason or "MARK_BLOCKED"
            return {"marked": False, "blocked": True}
        pos = self._position(isin, mark.symbol)
        if mark.quantity != pos.owned_qty:
            pos.blocked = True
            pos.blocked_reason = "MARK_QUANTITY_MISMATCH"
            return {"marked": False, "blocked": True,
                    "reason": "MARK_QUANTITY_MISMATCH"}
        return {"marked": True, "symbol": mark.symbol,
                "mark_paise": mark.mark_paise}

    def latest_marks(self, as_of_session: str | None = None) -> dict[str, ValuationMark]:
        marks: dict[str, ValuationMark] = {}
        for event in self.ledger.stream_records(self.stream_id, "VALUATION_MARK"):
            payload = event["payload"]
            if payload["status"] != "MARK_OBSERVED":
                continue
            symbol = payload["symbol"]
            session = payload.get("session_date") or _ist_date_of(payload["recorded_at"])
            if as_of_session and session > as_of_session:
                continue
            existing = marks.get(symbol)
            if existing is None or \
                    session > (existing.session_date or ""):
                marks[symbol] = ValuationMark(
                    stream_id=self.stream_id,
                    recorded_at=payload["recorded_at"],
                    maturity=payload["maturity"],
                    session_date=session,
                    symbol=symbol, isin=payload.get("isin"),
                    quantity=payload["quantity"],
                    mark_paise=payload["mark_paise"],
                    mark_source=payload["mark_source"],
                    mark_time=payload["mark_time"])
        return marks

    def nav(self, as_of_session: str | None = None) -> dict:
        """Verified equity/NAV; blocked positions fail closed (never invented)."""
        marks = self.latest_marks(as_of_session)
        positions: list[dict] = []
        equity_known = True
        holdings_value = 0
        invested_cost = 0
        for isin, pos in self.positions.items():
            qty = pos.owned_qty
            if qty == 0 and not pos.blocked:
                continue
            entry = {"symbol": pos.symbol, "isin": isin, "quantity": qty,
                     "settled": pos.settled_qty,
                     "pending_buy": pos.pending_buy_qty,
                     "pending_sell": pos.pending_sell_qty,
                     "blocked": pos.blocked}
            if pos.blocked:
                entry.update({"value_paise": None,
                              "status": "ACTION_BLOCKED",
                              "reason": pos.blocked_reason})
                equity_known = False
            elif pos.symbol in marks:
                mark = marks[pos.symbol]
                entry.update({"value_paise": qty * (mark.mark_paise or 0),
                              "status": "MARK_OBSERVED",
                              "mark_source": mark.mark_source,
                              "mark_time": mark.mark_time,
                              "mark_paise": mark.mark_paise})
                holdings_value += qty * (mark.mark_paise or 0)
                invested_cost += pos.cost_paise
            else:
                entry.update({"value_paise": None, "status": "NO_MARK"})
                equity_known = False
            positions.append(entry)
        equity = self.cash_paise + self.pending_proceeds_paise + holdings_value
        return {
            "stream_id": self.stream_id,
            "cash_paise": self.cash_paise,
            "pending_proceeds_paise": self.pending_proceeds_paise,
            "holdings_value_paise": holdings_value,
            "equity_paise": equity,
            "invested_cost_paise": invested_cost,
            "unrealised_pnl_paise": (holdings_value - invested_cost
                                      if equity_known else None),
            "realised_gross_paise": self.realised_gross_paise,
            "realised_net_paise": self.realised_net_paise,
            "fees_paid_paise": self.fees_paid_paise,
            "reserved_cash_paise": self.reserved_cash_paise,
            "reserved_shares": dict(self.reserved_shares),
            "nav_known": equity_known,
            "positions": positions,
            "fixture": self.fixture,
        }

    # -------------------------------------------------------- reconciliation --
    def reconcile(self) -> dict:
        """Independent cash/share conservation check from the ledger events.

        Cash: initial + dividends + buy costs (negative flows) + fees
        (negative) + net sale proceeds == book cash + pending proceeds.
        Holdings: fills and APPLIED split/bonus factors replayed in stream
        order must equal the live position map.
        """
        flows = self.ledger.stream_records(self.stream_id, "CASH_FLOW")
        dividends = sum(f["payload"]["amount_paise"] for f in flows
                        if f["payload"]["kind"] == "DIVIDEND")
        buy_cost = sum(f["payload"]["amount_paise"] for f in flows
                       if f["payload"]["kind"] == "BUY_COST")
        fees = sum(f["payload"]["amount_paise"] for f in flows
                   if f["payload"]["kind"] == "FEE")
        sell_proceeds = sum(f["payload"]["amount_paise"] for f in flows
                            if f["payload"]["kind"] in (
                                "SELL_PROCEEDS", "SELL_PROCEEDS_NET"))
        expected_cash = (self.initial_cash_paise + dividends
                          + buy_cost + fees + sell_proceeds)
        # Replay holdings in ledger order: fills +/- and verified split/bonus.
        expected_holdings: dict[str, int] = {}
        for event in self.ledger.records():
            if event["payload"].get("stream_id") != self.stream_id:
                continue
            payload = event["payload"]
            if event["event_type"] == "FILL_EVENT":
                if payload["fill_status"] not in (FILL_FILLED, FILL_PARTIAL):
                    continue
                isin = payload.get("isin") or payload["symbol"]
                qty = payload["filled_quantity"]
                expected_holdings[isin] = expected_holdings.get(isin, 0) + \
                    (qty if payload["side"] == "BUY" else -qty)
            elif event["event_type"] == "CORPORATE_ACTION_EVENT" and \
                    payload.get("status") == "APPLIED" and \
                    payload.get("action_kind") in ("SPLIT", "BONUS") and \
                    payload.get("factor"):
                isin = payload.get("isin")
                if isin and isin in expected_holdings:
                    expected_holdings[isin] = int(
                        expected_holdings[isin] * payload["factor"])
            elif event["event_type"] == "CORPORATE_ACTION_EVENT" and \
                    payload.get("status") == "APPLIED" and \
                    payload.get("action_kind") == "DEMERGER" and \
                    payload.get("child_isin") and \
                    payload.get("child_quantity_factor"):
                parent = payload.get("isin") or payload.get("symbol")
                parent_qty = expected_holdings.get(parent, 0)
                child_isin = payload["child_isin"]
                expected_holdings[child_isin] = expected_holdings.get(
                    child_isin, 0) + int(parent_qty * payload["child_quantity_factor"])
        expected_holdings = {k: v for k, v in expected_holdings.items() if v}
        actual_holdings = {isin: pos.owned_qty for isin, pos in self.positions.items()
                           if pos.owned_qty or isin in expected_holdings}
        cash_ok = expected_cash == self.cash_paise + self.pending_proceeds_paise
        holdings_ok = expected_holdings == actual_holdings
        no_negative = self.cash_paise >= 0 and self.pending_proceeds_paise >= 0
        reservations_ok = (self.reserved_cash_paise >= 0
                           and all(value >= 0 for value in self.reserved_shares.values()))
        return {
            "cash_conserved": cash_ok,
            "expected_cash_plus_pending_paise": expected_cash,
            "actual_cash_plus_pending_paise":
                self.cash_paise + self.pending_proceeds_paise,
            "holdings_conserved": holdings_ok,
            "expected_holdings": expected_holdings,
            "actual_holdings": actual_holdings,
            "no_negative_balances": no_negative,
            "reservations_valid": reservations_ok,
            "ok": cash_ok and holdings_ok and no_negative and reservations_ok,
        }
