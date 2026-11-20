// Renders demo-result.json into report.html and captures screenshots with Playwright.
// Run: node audit/demo/final-submission-2026-11-20/render-report.mjs
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const d = JSON.parse(readFileSync(join(HERE, "demo-result.json"), "utf8"));
const inr = (v) =>
  v == null
    ? "—"
    : "₹" +
      Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
const ist = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }) + " IST"
    : "—";
const rows = (list, cols) =>
  `<table><thead><tr>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${list
    .map((r) => `<tr>${cols.map((c) => `<td>${c[1](r)}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;

const o = d.order,
  f = d.fills[0],
  a = d.account,
  h = d.holdings[0],
  p = d.protections[0],
  q = d.quote_used_for_fill;
const banner = `<div class="banner">DEMO TRADE — isolated ₹1,00,000 virtual account <code>${esc(d.book_id)}</code>.
Not a V2 or V3.1 forward-study trade. Paper only, so no broker order was sent. Brokerage is assumed ₹0 (BROKER_ASSUMPTION) and has not been checked against the FYERS account.</div>`;

const html = `<!doctype html><html><head><meta charset="utf-8"><title>Quant Plus Paper Demo</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#2a2f3a;--text:#e7e9ee;--muted:#9aa3b2;--ok:#3ecf8e;--bad:#ff6b6b;--warn:#f5a524}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:0 0 12px}
.sub{color:var(--muted);margin-bottom:16px}
.banner{background:#3a2a05;border:2px solid var(--warn);color:#ffd27a;padding:12px 14px;border-radius:8px;font-weight:600;margin:12px 0 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:13px} th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500} code{font-size:12px;color:#c9d1ff;overflow-wrap:anywhere;word-break:break-word}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px} .kpi b{display:block;font-size:18px} .kpi span{color:var(--muted);font-size:12px}
.PASS{color:var(--ok);font-weight:600} .FAIL{color:var(--bad);font-weight:600} .tag{display:inline-block;padding:1px 6px;border-radius:4px;background:#2a2f3a;font-size:11px}
.assume{color:var(--warn);font-weight:600}
</style></head><body><main>
<h1>Quant Plus: Paper-Trading Demonstration</h1>
<div class="sub">Generated ${esc(ist(d.generated_at))} · deterministic TypeScript paper-book engine · fee schedule <code>${esc(d.fee_schedule.id)}</code></div>
${banner}

<section id="validation"><h2>1. Order validation (fails closed on any FAIL)</h2>
${rows(d.validation_checks, [
  ["Check", (r) => `<code>${esc(r.check)}</code>`],
  ["Result", (r) => `<span class="${r.result}">${r.result}</span>`],
  ["Detail", (r) => esc(r.detail)],
])}
</section>

<section id="quote"><h2>2. Server-observed FYERS quote used for the fill</h2>
<table><tbody>
<tr><th>Symbol</th><td>${esc(q.symbol)}</td><th>Source</th><td>${esc(q.source)} (delayed: ${q.delayed}, stale: ${q.stale})</td></tr>
<tr><th>Last</th><td>${inr(q.price)}</td><th>Bid / Ask</th><td>${inr(q.bid)} × ${q.bid_size} / ${inr(q.ask)} × ${q.ask_size}</td></tr>
<tr><th>Provider time</th><td>${esc(ist(q.as_of))}</td><th>Received</th><td>${esc(ist(q.received_at))}</td></tr>
<tr><th>Session</th><td>${esc(q.market_session)}</td><th>Decision</th><td>${esc(ist(q.decision_at))}</td></tr>
</tbody></table></section>

<section id="execution"><h2>3. Execution / fill</h2>
<table><tbody>
<tr><th>Order</th><td><code>${esc(o.id)}</code></td><th>Intent</th><td><code>${esc(o.intent_id)}</code></td></tr>
<tr><th>Instruction</th><td>${o.side} ${o.quantity} ${esc(o.symbol)} · ${o.order_type} · ${o.product} · ${o.validity}</td><th>Status</th><td class="PASS">${o.status} (${o.filled_quantity}/${o.quantity})</td></tr>
<tr><th>Fill price</th><td>${inr(f.price)} (reference last ${inr(f.reference_price)})</td><th>Fill method</th><td>${esc(f.method)} · slippage ${f.slippage_bps} bps · liquidity-limited: ${f.liquidity_limited}</td></tr>
<tr><th>Executed value</th><td>${inr(f.price * f.quantity)}</td><th>T+1 settlement due</th><td>${esc(ist(f.settlement_due_at))}</td></tr>
</tbody></table></section>

<section id="charges"><h2>4. Brokerage and charges (schedule <code>${esc(f.charges.schedule)}</code>)</h2>
${rows(f.charges.items, [
  ["Item", (r) => esc(r.label)],
  [
    "Category",
    (r) =>
      r.category === "BROKER_ASSUMPTION"
        ? `<span class="assume">${r.category}</span>`
        : `<span class="tag">${r.category}</span>`,
  ],
  ["Basis", (r) => esc(r.basis)],
  ["Amount", (r) => inr(r.amount)],
])}
<p><b>Total charges: ${inr(f.charges.total)}</b> (pre-trade estimate ${inr(d.pre_trade_estimate.total_paise / 100)}). <span class="assume">Brokerage ₹0 is an assumption. It has not been checked against the FYERS account.</span></p>
</section>

<section id="ledger"><h2>5. Cash ledger</h2>
${rows(d.cash_ledger, [
  ["Seq", (r) => r.seq],
  ["Kind", (r) => r.kind],
  ["Amount", (r) => inr(r.amount)],
  ["Balance after", (r) => inr(r.balance_after)],
  ["Note", (r) => esc(r.note)],
])}
<div class="kpis" style="margin-top:12px">
<div class="kpi"><span>Wallet balance</span><b>${inr(a.wallet_balance)}</b></div>
<div class="kpi"><span>Available cash</span><b>${inr(a.available_cash)}</b></div>
<div class="kpi"><span>Reserved cash</span><b>${inr(a.reserved_cash)}</b></div>
<div class="kpi"><span>Charges paid</span><b>${inr(a.charges_paid)}</b></div>
</div></section>

<section id="positions"><h2>6. Positions</h2>
${rows(d.holdings, [
  ["Symbol", (r) => esc(r.symbol)],
  ["Qty", (r) => r.quantity],
  ["Settled / unsettled", (r) => `${r.settled_quantity} / ${r.unsettled_quantity}`],
  ["Avg price", (r) => inr(r.avg_price)],
  ["Cost basis", (r) => inr(r.cost_basis)],
  ["Mark", (r) => `${inr(r.last_price)} (${esc(r.mark_source)}, fresh: ${r.mark_fresh})`],
])}
</section>

<section id="risk"><h2>7. Risk management</h2>
<table><tbody>
<tr><th>Pre-trade guard</th><td colspan="3">${esc(d.validation_checks.find((c) => c.check === "risk_guard_rejects_oversized_order").detail)}</td></tr>
<tr><th>Protective stop / target</th><td>${inr(p.stop_loss)} / ${inr(p.target_price)} (3% below / 5% above entry ask)</td><th>Protection</th><td>${esc(p.status)} · ${p.remaining_quantity} shares</td></tr>
<tr><th>Max position</th><td>${d.risk_limits.max_position_pct}% of equity</td><th>Max order value</th><td>${inr(d.risk_limits.max_order_value)}</td></tr>
<tr><th>Daily loss limit</th><td>${inr(d.risk_status.daily_loss_limit)}</td><th>Day loss / blocked</th><td>${inr(d.risk_status.day_loss)} / ${d.risk_status.blocked}</td></tr>
</tbody></table>
<p class="sub">The stop and target are demo parameters chosen for this demonstration. No AI signal was used.</p></section>

<section id="nav"><h2>8. Portfolio NAV</h2>
<div class="kpis">
<div class="kpi"><span>Starting virtual capital</span><b>${inr(a.total_funds)}</b></div>
<div class="kpi"><span>Cash</span><b>${inr(a.wallet_balance)}</b></div>
<div class="kpi"><span>Position at mark</span><b>${inr(h.last_price * h.quantity)}</b></div>
<div class="kpi"><span>NAV</span><b>${inr(d.nav.nav_rupees)}</b></div>
<div class="kpi"><span>Change vs capital</span><b>${inr(d.nav.change_vs_capital_rupees)}</b></div>
</div>
<p class="sub">${esc(d.nav.note)} Change = −${inr(a.charges_paid)} charges + ${inr((h.last_price - h.avg_price) * h.quantity)} mark-to-market (mark ${inr(h.last_price)} vs fill ${inr(h.avg_price)}). Mark source: ${esc(d.quote_used_for_mark.note)}${d.quote_used_for_mark.as_of === q.as_of ? " — the second fetch returned the same provider tick as the fill quote" : ""} (provider time ${esc(ist(d.quote_used_for_mark.as_of))}).</p></section>

<section id="audit"><h2>9. Order audit trail</h2>
${rows(d.order_audit_events, [
  ["Seq", (r) => r.seq],
  ["Event", (r) => `<code>${esc(r.type)}</code>`],
  ["Entity", (r) => esc(r.entity)],
  ["At", (r) => esc(ist(r.at))],
  ["Data", (r) => `<code>${esc(JSON.stringify(r.data))}</code>`],
])}
<p>Reconciliation: <span class="PASS">${d.book_report.reconciliation.length === 0 ? "PASS (cash = ledger, positions = fills, charges, unique monotonic sequence)" : esc(d.book_report.reconciliation.join("; "))}</span></p></section>

<section id="isolation"><h2>10. Isolation and preservation</h2>
${rows(Object.keys(d.isolation.protected_files_sha256_before), [
  ["Protected file", (k) => `<code>${esc(k)}</code>`],
  [
    "SHA-256 before = after",
    (k) =>
      d.isolation.protected_files_sha256_before[k] === d.isolation.protected_files_sha256_after[k]
        ? `<span class="PASS">unchanged</span> <code>${d.isolation.protected_files_sha256_after[k].slice(0, 16)}…</code>`
        : `<span class="FAIL">CHANGED</span>`,
  ],
])}
<p>Broker order API called: <b>${d.isolation.broker_order_api_called}</b>. ${esc(d.isolation.writes)}. ${esc(d.fee_schedule.v31_fee_gate)}</p></section>
</main></body></html>`;

writeFileSync(join(HERE, "report.html"), html);
const shots = join(HERE, "screenshots");
mkdirSync(shots, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1200, height: 900 },
  deviceScaleFactor: 1.5,
});
await page.goto("file:///" + join(HERE, "report.html").replace(/\\/g, "/"));
await page.screenshot({ path: join(shots, "00-full-report.png"), fullPage: true });
const names = [
  "validation",
  "quote",
  "execution",
  "charges",
  "ledger",
  "positions",
  "risk",
  "nav",
  "audit",
  "isolation",
];
for (const [i, id] of names.entries()) {
  // Each section shot includes the DEMO banner above it so no image can be cropped without the label.
  await page.evaluate((target) => {
    for (const s of document.querySelectorAll("section"))
      s.style.display = s.id === target ? "" : "none";
  }, id);
  await page
    .locator("main")
    .screenshot({ path: join(shots, `${String(i + 1).padStart(2, "0")}-${id}.png`) });
}
await browser.close();
console.log("report.html + screenshots written");
