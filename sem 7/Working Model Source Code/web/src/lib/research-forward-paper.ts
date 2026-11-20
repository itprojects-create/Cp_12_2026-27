/**
 * Wave 6 adapter to the existing deterministic paper-book engine.
 *
 * This module creates no broker surface and fetches no quote. A reviewed
 * server worker must inject a provider observation. The isolated
 * `research_v3` namespace never aliases the user's main/practice account.
 */
import { exchangeSession } from "./exchange-calendar.ts";
import type { ForwardBrokerPlan } from "./paper-fees.ts";
import { fundWallet, placeOrder, reconcile, type PlaceInput } from "./paper-book/engine.ts";
import type { BookState, Clock, QuoteObservation } from "./paper-book/types.ts";
import { settlementBalances } from "./paper-book/settlement.ts";

export const RESEARCH_FORWARD_BOOK = "research_v3" as const;

export type ForwardPaperEnvelope = {
  stream_id: string;
  maturity: "ENGINEERING_FIXTURE" | "ELIGIBLE_PAPER_PORTFOLIO";
  approval_ref: string | null;
  decision_cutoff: string;
  intent_id: string;
  symbol: string;
  isin: string;
  side: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT" | "STOP";
  quantity: number;
  limit_paise: number | null;
  broker_plan: ForwardBrokerPlan;
};

function timestamp(value: string, code: string) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new Error(code);
  return parsed;
}

export function configureForwardResearchBook(
  state: BookState,
  clock: Clock,
  envelope: ForwardPaperEnvelope,
  initialCapitalPaise: number,
) {
  if (!Number.isSafeInteger(initialCapitalPaise) || initialCapitalPaise <= 0)
    throw new Error("INVALID_INITIAL_CAPITAL");
  if (envelope.maturity === "ELIGIBLE_PAPER_PORTFOLIO" && !envelope.approval_ref)
    throw new Error("OPERATOR_APPROVAL_REQUIRED");
  const prior = state.research_forward;
  if (prior && prior.stream_id !== envelope.stream_id) throw new Error("RESEARCH_STREAM_CONFLICT");
  state.research_forward = {
    stream_id: envelope.stream_id,
    authority: envelope.maturity,
    broker_plan: envelope.broker_plan,
    isin_by_symbol: { ...(prior?.isin_by_symbol ?? {}), [envelope.symbol]: envelope.isin },
    operator_approval_ref: envelope.approval_ref,
  };
  if (state.account.net_deposits_paise === 0)
    fundWallet(state, clock, initialCapitalPaise, "DEPOSIT");
  else if (state.account.net_deposits_paise !== initialCapitalPaise)
    throw new Error("INITIAL_CAPITAL_IMMUTABLE");
}

export function executeForwardPaperIntent(
  state: BookState,
  clock: Clock,
  envelope: ForwardPaperEnvelope,
  observation: QuoteObservation,
) {
  const config = state.research_forward;
  if (!config || config.stream_id !== envelope.stream_id) throw new Error("STREAM_NOT_CONFIGURED");
  if (config.authority !== envelope.maturity) throw new Error("EVIDENCE_LANE_MISMATCH");
  if (envelope.maturity === "ELIGIBLE_PAPER_PORTFOLIO" && !config.operator_approval_ref)
    throw new Error("OPERATOR_APPROVAL_REQUIRED");
  if (observation.symbol !== envelope.symbol) throw new Error("INVALID_SYMBOL");
  if (config.isin_by_symbol[envelope.symbol] !== envelope.isin) throw new Error("UNKNOWN_ISIN");
  const cutoff = timestamp(envelope.decision_cutoff, "INVALID_DECISION_CUTOFF");
  const provider = timestamp(observation.provider_time, "INVALID_PROVIDER_TIME");
  const received = timestamp(observation.received_at, "INVALID_RECEIVED_TIME");
  if (provider <= cutoff || received <= cutoff) throw new Error("QUOTE_NOT_AFTER_DECISION");
  if (provider > received || received > clock.now) throw new Error("FUTURE_QUOTE");
  if (observation.stale || observation.delayed) throw new Error("QUOTE_STALE");
  if (clock.now - provider > 60_000) throw new Error("QUOTE_STALE");
  if (envelope.maturity === "ENGINEERING_FIXTURE") {
    if (observation.provider !== "fixture") throw new Error("FIXTURE_PROVIDER_REQUIRED");
  } else if (observation.provider !== "fyers") {
    throw new Error("ELIGIBLE_PROVIDER_REQUIRED");
  }
  const session = exchangeSession(clock.now);
  if (!session.verified || !session.open || observation.market_session !== "open")
    throw new Error("SESSION_CLOSED_UNVERIFIED_OR_HOLIDAY");
  if (envelope.side === "SELL") {
    const settlement = settlementBalances(state, clock.now);
    const holding = settlement.holdings.get(envelope.symbol);
    if (settlement.unverified_fills || holding?.settled_quantity == null)
      throw new Error("SETTLEMENT_UNVERIFIED");
    if (holding.settled_quantity < envelope.quantity)
      throw new Error("DELIVERY_SETTLED_SHARES_REQUIRED");
  }
  const input: PlaceInput = {
    intent_id: envelope.intent_id,
    symbol: envelope.symbol,
    company: envelope.symbol,
    side: envelope.side,
    order_type: envelope.order_type,
    quantity: envelope.quantity,
    limit_price: envelope.limit_paise == null ? null : envelope.limit_paise / 100,
    stop_loss: null,
    target_price: null,
    trailing_stop: null,
    execution_mode: "LIVE",
  };
  const order = placeOrder(state, clock, input, observation);
  const problems = reconcile(state);
  if (problems.length) throw new Error(`RECONCILIATION_FAILED:${problems.join("|")}`);
  return order;
}
