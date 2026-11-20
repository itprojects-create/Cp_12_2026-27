import assert from "node:assert/strict";
import test from "node:test";
import { clockAt } from "./paper-book/types.ts";
import { newBook } from "./paper-book/engine.ts";
import { deliveryCharges, forwardDeliveryCharges } from "./paper-fees.ts";
import {
  configureForwardResearchBook,
  executeForwardPaperIntent,
  RESEARCH_FORWARD_BOOK,
  type ForwardPaperEnvelope,
} from "./research-forward-paper.ts";

const at = (iso: string) => clockAt(Date.parse(iso));
const baseEnvelope = (overrides: Partial<ForwardPaperEnvelope> = {}): ForwardPaperEnvelope => ({
  stream_id: "w6-fixture-stream",
  maturity: "ENGINEERING_FIXTURE",
  approval_ref: null,
  decision_cutoff: "2026-11-16T04:20:00.000Z",
  intent_id: "w6-fixture-buy-0001",
  symbol: "TCS",
  isin: "INE467B01029",
  side: "BUY",
  order_type: "MARKET",
  quantity: 10,
  limit_paise: null,
  broker_plan: "fyers_standard_observed_2026_11_14",
  ...overrides,
});

const quote = (overrides: Record<string, unknown> = {}) => ({
  symbol: "TCS",
  price_paise: 10_000,
  bid_paise: 9_999,
  ask_paise: 10_001,
  bid_size: 100,
  ask_size: 100,
  provider: "fixture",
  provider_time: "2026-11-16T04:29:30.000Z",
  received_at: "2026-11-16T04:29:40.000Z",
  decision_at: "2026-11-16T04:20:00.000Z",
  market_session: "open",
  delayed: false,
  stale: false,
  change_pct: 0,
  ...overrides,
});

test("research adapter uses a separate namespace and the existing book engine", () => {
  assert.equal(RESEARCH_FORWARD_BOOK, "research_v3");
  const state = newBook("research:w6", at("2026-11-16T04:30:00.000Z"));
  const envelope = baseEnvelope();
  configureForwardResearchBook(state, at("2026-11-16T04:30:00.000Z"), envelope, 1_000_000);
  const order = executeForwardPaperIntent(state, at("2026-11-16T04:30:00.000Z"), envelope, quote());
  assert.equal(order.status, "FILLED");
  assert.equal(state.fills.length, 1);
  assert.equal(state.fills[0]!.isin, "INE467B01029");
  assert.equal(state.fills[0]!.broker_plan, "fyers_standard_observed_2026_11_14");
});

test("eligible lane requires explicit paper-only operator approval", () => {
  const state = newBook("research:w6", at("2026-11-16T04:30:00.000Z"));
  const envelope = baseEnvelope({ maturity: "ELIGIBLE_PAPER_PORTFOLIO" });
  assert.throws(
    () => configureForwardResearchBook(state, at("2026-11-16T04:30:00.000Z"), envelope, 1_000_000),
    /OPERATOR_APPROVAL_REQUIRED/,
  );
});

test("decision quote must be contemporaneous, fresh and after cutoff", () => {
  const state = newBook("research:w6", at("2026-11-16T04:30:00.000Z"));
  const envelope = baseEnvelope();
  configureForwardResearchBook(state, at("2026-11-16T04:30:00.000Z"), envelope, 1_000_000);
  assert.throws(
    () =>
      executeForwardPaperIntent(
        state,
        at("2026-11-16T04:30:00.000Z"),
        envelope,
        quote({ provider_time: "2026-11-16T04:19:59.000Z" }),
      ),
    /QUOTE_NOT_AFTER_DECISION/,
  );
  assert.equal(state.fills.length, 0);
});

test("delivery-only adapter refuses a same-day sell of unsettled shares", () => {
  const state = newBook("research:w6", at("2026-11-16T04:30:00.000Z"));
  const buy = baseEnvelope();
  configureForwardResearchBook(state, at("2026-11-16T04:30:00.000Z"), buy, 1_000_000);
  executeForwardPaperIntent(state, at("2026-11-16T04:30:00.000Z"), buy, quote());
  const sell = baseEnvelope({
    intent_id: "w6-fixture-sell-0001",
    side: "SELL",
    decision_cutoff: "2026-11-16T04:31:00.000Z",
  });
  const sellQuote = quote({
    provider_time: "2026-11-16T04:31:30.000Z",
    received_at: "2026-11-16T04:31:40.000Z",
    decision_at: "2026-11-16T04:31:00.000Z",
  });
  assert.throws(
    () => executeForwardPaperIntent(state, at("2026-11-16T04:32:00.000Z"), sell, sellQuote),
    /DELIVERY_SETTLED_SHARES_REQUIRED/,
  );
  assert.equal(state.fills.length, 1);
});

test("forward plan adds per-order brokerage and DP only once per ISIN/day", () => {
  const buy = forwardDeliveryCharges(
    "BUY",
    10_000_000,
    "2026-11-16T04:30:00.000Z",
    "fyers_standard_observed_2026_11_14",
  );
  assert.equal(buy.items.find((item) => item.code === "BROKERAGE")!.amount_paise, 2_000);
  const sell1 = forwardDeliveryCharges(
    "SELL",
    10_000_000,
    "2026-11-17T04:30:00.000Z",
    "fyers_standard_observed_2026_11_14",
    true,
    true,
  );
  const sell2 = forwardDeliveryCharges(
    "SELL",
    10_000_000,
    "2026-11-17T05:30:00.000Z",
    "fyers_standard_observed_2026_11_14",
    true,
    false,
  );
  assert.equal(sell1.items.find((item) => item.code === "DP")!.amount_paise, 1_250);
  assert.equal(sell2.items.find((item) => item.code === "DP")!.amount_paise, 0);
  assert.equal(sell1.total_paise - sell2.total_paise, 1_475);
});

test("current pages are never back-projected and legacy book fees stay unchanged", () => {
  assert.throws(
    () =>
      forwardDeliveryCharges(
        "BUY",
        1_000_000,
        "2026-11-13T04:30:00.000Z",
        "fyers_standard_observed_2026_11_14",
      ),
    /CHARGE_SCHEDULE_UNAVAILABLE/,
  );
  assert.equal(deliveryCharges("BUY", 10_000_000, "2026-11-16T04:30:00.000Z").total_paise, 11_874);
});
