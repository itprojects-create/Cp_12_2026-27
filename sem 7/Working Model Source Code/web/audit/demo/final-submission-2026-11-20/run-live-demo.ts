/**
 * FINAL-SUBMISSION PAPER-TRADING DEMONSTRATION (DEMO ONLY — NOT A FORWARD-STUDY TRADE)
 *
 * - Isolated in-memory demo book "demo:final-submission-2026-11-20", ₹1,00,000 virtual capital.
 * - Uses the existing deterministic engine (src/lib/paper-book/engine.ts) unchanged.
 * - Fee schedule: app default nse-cm-delivery-2026-03-01 (brokerage = BROKER_ASSUMPTION zero,
 *   NOT verified against the operator's FYERS account). No research_forward config is attached,
 *   so no V3.1 broker-plan path is used.
 * - Quote: one fresh server-observed FYERS quote from the local market-data service, validated
 *   with the app's own execution policy. Any failed check FAILS CLOSED (no order, exit 2).
 * - Never touches the main/practice/hosted books, the V2 forecast ledger or V3.1 ledgers; it
 *   writes only into this folder. It never calls a broker order API.
 *
 * Run: node --experimental-strip-types audit/demo/final-submission-2026-11-20/run-live-demo.ts
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { exchangeSession } from "../../../src/lib/exchange-calendar.ts";
import { deliveryCharges } from "../../../src/lib/paper-fees.ts";
import { executionQuoteError } from "../../../src/lib/quote-eligibility.ts";
import {
  fundWallet,
  markHolding,
  markedEquity,
  newBook,
  observationFromQuote,
  placeOrder,
  reconcile,
} from "../../../src/lib/paper-book/engine.ts";
import { clockAt, type BookState } from "../../../src/lib/paper-book/types.ts";
import {
  accountView,
  bookReport,
  fillView,
  holdingView,
  ledgerView,
  observationView,
  orderView,
  protectionView,
  riskLimitsView,
  riskStatusView,
} from "../../../src/lib/paper-book/views.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..", "..");
const BOOK_ID = "demo:final-submission-2026-11-20";
const SYMBOL = "TCS";
const QUANTITY = 10;
const CAPITAL_PAISE = 1_00_000_00;
const EXPECTED_SCHEDULE = "nse-cm-delivery-2026-03-01";
const LABEL = "DEMO — isolated virtual account; not a V2/V3.1 forward-study trade; no real order";

const PROTECTED = [
  ".local-data/workspace.json",
  "reports/alpha_v3_1/wave6_engineering_fixture_ledger.jsonl",
  "reports/alpha_v3_1/wave6_signal_and_paper_ledger.jsonl",
  "reports/alpha_v3_1/wave6_paper_nav_and_benchmark.json",
  "backend-extension/data/forecast_reports/ledger_heads.jsonl",
  "backend-extension/data/forecast_reports/paper_pnl.jsonl",
  "backend-extension/data/research_v3/warehouse.sqlite3",
  "src/lib/paper-book/engine.ts",
  "src/lib/paper-fees.ts",
];
const hashes = () =>
  Object.fromEntries(
    PROTECTED.map((p) => {
      const full = join(ROOT, p);
      return [
        p,
        existsSync(full) ? createHash("sha256").update(readFileSync(full)).digest("hex") : "ABSENT",
      ];
    }),
  );

function envValue(name: string) {
  const text = readFileSync(join(ROOT, ".env.local"), "utf8");
  const match = text.match(new RegExp(`^\\s*${name}\\s*=\\s*(.*)$`, "m"));
  return match ? match[1]!.trim().replace(/^["']|["']$/g, "") : "";
}

async function fetchProviderQuote(symbol: string) {
  // Same request as src/lib/provider-quote.server.ts (read-only market data, no order API).
  const base = (envValue("AGENT_SERVICE_URL") || "http://127.0.0.1:8000").replace(/\/$/, "");
  const key = envValue("AGENT_SERVICE_API_KEY");
  if (!key) throw new Error("PREREQ_MARKET_DATA_AUTH_MISSING");
  const res = await fetch(`${base}/api/v1/market/${encodeURIComponent(symbol)}/quote`, {
    headers: { "X-Quantplus-Key": key },
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`PREREQ_QUOTE_HTTP_${res.status}`);
  const quote = (await res.json()) as Record<string, unknown>;
  return { ...quote, received_at: new Date().toISOString() };
}

const out = (name: string, data: unknown) =>
  writeFileSync(join(HERE, name), JSON.stringify(data, null, 2) + "\n");

async function main() {
  if (existsSync(join(HERE, "demo-book.json")))
    throw new Error("DEMO_ALREADY_EXECUTED (refusing to place a second demo order)");
  const before = hashes();
  const checks: { check: string; result: "PASS" | "FAIL"; detail: string }[] = [];
  const pass = (check: string, ok: boolean, detail: string) => {
    checks.push({ check, result: ok ? "PASS" : "FAIL", detail });
    if (!ok) throw Object.assign(new Error(`FAIL_CLOSED:${check}`), { checks });
  };

  // ---- prerequisite: fee schedule (app default, brokerage assumption disclosed)
  const probe = deliveryCharges("BUY", 1_000_000, new Date().toISOString());
  pass("fee_schedule_id", probe.schedule === EXPECTED_SCHEDULE, probe.schedule);
  const brokerage = probe.items.find((i) => i.code === "BROKERAGE");
  pass(
    "brokerage_is_disclosed_assumption",
    brokerage?.category === "BROKER_ASSUMPTION" && brokerage.amount_paise === 0,
    `${brokerage?.category} ${brokerage?.amount_paise} paise — assumed zero, NOT verified against the FYERS account`,
  );

  // ---- prerequisite: verified open exchange session
  const session = exchangeSession(Date.now());
  pass(
    "exchange_session_verified_open",
    session.verified && session.open,
    JSON.stringify(session.day ?? session),
  );

  // ---- prerequisite: fresh server-observed FYERS quote
  const raw = await fetchProviderQuote(SYMBOL);
  const decision = clockAt();
  const policyError = executionQuoteError(raw, decision.now, "LIVE", SYMBOL);
  pass(
    "quote_execution_policy_LIVE",
    policyError === null,
    policyError ?? "source=fyers, not delayed, not stale, open session, <=60s old",
  );
  pass("quote_source_fyers", raw["source"] === "fyers", String(raw["source"]));
  const observation = observationFromQuote(raw, decision, decision);
  pass(
    "quote_has_bid_ask",
    observation.bid_paise != null && observation.ask_paise != null,
    `bid ${observation.bid_paise} / ask ${observation.ask_paise} paise`,
  );

  // ---- isolated demo book
  const state: BookState = newBook(BOOK_ID, decision);
  pass(
    "book_isolated_no_research_forward",
    state.research_forward === undefined,
    "no V3.1 config attached",
  );
  fundWallet(state, decision, CAPITAL_PAISE, "DEPOSIT");

  // ---- risk management demonstration: an oversized order is rejected on a scratch copy
  const scratch = structuredClone(state);
  let oversized = "NOT_REJECTED";
  try {
    placeOrder(
      scratch,
      decision,
      {
        intent_id: "demo-risk-probe-oversized",
        symbol: SYMBOL,
        company: "Tata Consultancy Services",
        side: "BUY",
        order_type: "MARKET",
        quantity: 20,
        limit_price: null,
        stop_loss: null,
        target_price: null,
        trailing_stop: null,
        execution_mode: "LIVE",
      },
      observation,
    );
  } catch (error) {
    oversized = (error as Error).message;
  }
  pass(
    "risk_guard_rejects_oversized_order",
    oversized === "POSITION_VALUE_LIMIT",
    `20 × TCS → ${oversized} (max ${state.risk_limits.max_position_pct}% of equity); scratch copy discarded`,
  );

  // ---- the one DEMO order: MARKET BUY 10 TCS with protective stop/target
  const ask = observation.ask_paise!;
  const stopPaise = Math.round((ask * 0.97) / 5) * 5; // 3% below, 0.05 tick
  const targetPaise = Math.round((ask * 1.05) / 5) * 5; // 5% above, 0.05 tick
  const estimate = deliveryCharges("BUY", QUANTITY * ask, decision.iso);
  const order = placeOrder(
    state,
    decision,
    {
      intent_id: "demo-final-submission-tcs-buy-0001",
      symbol: SYMBOL,
      company: "Tata Consultancy Services",
      side: "BUY",
      order_type: "MARKET",
      quantity: QUANTITY,
      limit_price: null,
      stop_loss: stopPaise / 100,
      target_price: targetPaise / 100,
      trailing_stop: null,
      execution_mode: "LIVE",
    },
    observation,
  );
  pass(
    "order_filled",
    order.status === "FILLED",
    `${order.status} ${order.filled_quantity}/${order.quantity}`,
  );
  const problems = reconcile(state);
  pass(
    "reconciliation_after_fill",
    problems.length === 0,
    problems.join("; ") || "cash=ledger, positions=fills, charges, seq OK",
  );

  // ---- portfolio NAV from a second fresh observed quote (mark only, never invented)
  const markRaw = await fetchProviderQuote(SYMBOL);
  const markClock = clockAt();
  const markError = executionQuoteError(markRaw, markClock.now, "LIVE", SYMBOL);
  let markNote = "mark = fill-time observation";
  if (markError === null) {
    markHolding(state, observationFromQuote(markRaw, markClock));
    markNote = "mark = second fresh FYERS observation";
  } else markNote = `second quote not markable (${markError}); mark kept at fill-time observation`;
  const nav = markedEquity(state, markClock.now);
  pass("reconciliation_after_mark", reconcile(state).length === 0, "OK");

  const after = hashes();
  const changed = PROTECTED.filter((p) => before[p] !== after[p]);

  const result = {
    label: LABEL,
    status: "LIVE_PAPER_DEMO_EXECUTED",
    book_id: BOOK_ID,
    generated_at: new Date().toISOString(),
    fee_schedule: {
      id: EXPECTED_SCHEDULE,
      brokerage:
        "BROKER_ASSUMPTION = ₹0. Assumed zero; NOT verified against the operator's FYERS account.",
      v31_fee_gate:
        "Unchanged: DATA_BLOCKED / OPERATOR_ACCOUNT_PLAN_NOT_CONFIRMED (not used here).",
    },
    validation_checks: checks,
    quote_used_for_fill: observationView(observation),
    quote_used_for_mark: {
      ...observationView(observationFromQuote(markRaw, markClock)),
      note: markNote,
    },
    pre_trade_estimate: estimate,
    order: orderView(order),
    fills: state.fills.map(fillView),
    account: accountView(state),
    holdings: state.holdings.map((h) => holdingView(state, h, markClock.now)),
    protections: state.protections.map(protectionView),
    cash_ledger: state.ledger.map(ledgerView),
    risk_limits: riskLimitsView(state),
    risk_status: riskStatusView(state, markClock),
    nav: {
      nav_paise: nav.equity,
      nav_rupees: nav.equity / 100,
      stale_marks: nav.stale,
      change_vs_capital_rupees: (nav.equity - CAPITAL_PAISE) / 100,
      note: "Mark-to-market of an open demo position minutes after entry. Not realised profit, not a performance claim.",
    },
    order_audit_events: state.events,
    book_report: bookReport(state),
    isolation: {
      protected_files_sha256_before: before,
      protected_files_sha256_after: after,
      changed_protected_files: changed,
      writes: "Only files in audit/demo/final-submission-2026-11-20/",
      broker_order_api_called: false,
    },
  };
  out("demo-book.json", state);
  out("demo-result.json", result);
  console.log(
    JSON.stringify(
      { status: result.status, order: result.order, nav: result.nav, changed },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  const checks = (error as { checks?: unknown }).checks ?? [];
  out("demo-fail-closed.json", {
    label: LABEL,
    status: "FAIL_CLOSED",
    reason: (error as Error).message,
    validation_checks: checks,
    at: new Date().toISOString(),
    action:
      "No order placed. Only the verified engineering fixture may be replayed, labelled OFFLINE SIMULATION.",
  });
  console.error("FAIL_CLOSED:", (error as Error).message);
  process.exit(2);
});
