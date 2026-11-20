// Feature-tour screenshots. Run against an ISOLATED local-profile server (port 4180,
// throwaway book in .local-data/screenshot-tour). The login page is captured read-only from
// the hosted-mode dev server (port 8080) without signing in.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "shots");
mkdirSync(OUT, { recursive: true });
const BASE = "http://127.0.0.1:4180";
const HOSTED = "http://127.0.0.1:8080";

const pages = [
  ["01-landing", BASE + "/"],
  ["02-login", HOSTED + "/auth"],
  ["03-platform", BASE + "/platform"],
  ["04-markets-public", BASE + "/markets"],
  ["05-research-public", BASE + "/research"],
  ["06-ai-public", BASE + "/ai"],
  ["10-home-dashboard", BASE + "/app/dashboard"],
  ["11-discover-markets", BASE + "/app/markets"],
  ["12-stock-trading-RELIANCE", BASE + "/app/stocks/RELIANCE"],
  ["13-watchlist", BASE + "/app/watchlist"],
  ["14-screener", BASE + "/app/screener"],
  ["15-events-news-sentiment", BASE + "/app/events"],
  ["16-ripple-map", BASE + "/app/ripple"],
  ["17-market-context-regime", BASE + "/app/regime"],
  ["18-research", BASE + "/app/research"],
  ["19-option-chain", BASE + "/app/options"],
  ["20-portfolio", BASE + "/app/portfolio"],
  ["21-orders", BASE + "/app/orders"],
  ["22-wallet", BASE + "/app/wallet"],
  ["23-risk", BASE + "/app/risk"],
  ["24-alerts", BASE + "/app/alerts"],
  ["25-basket", BASE + "/app/basket"],
  ["26-exposure-xray", BASE + "/app/xray"],
  ["27-ai-assistant", BASE + "/app/quant-ai"],
  ["28-ai-debate-committee", BASE + "/app/committee"],
  ["29-research-trace", BASE + "/app/agent-activity"],
  ["30-verdict-details", BASE + "/app/decisions"],
  ["31-track-record", BASE + "/app/track-record"],
  ["32-strategy-lab", BASE + "/app/strategy-lab"],
  ["33-history", BASE + "/app/history"],
  ["34-review-journal", BASE + "/app/journal"],
  ["35-trading-habits", BASE + "/app/behavior"],
  ["36-replay", BASE + "/app/replay"],
  ["37-learn", BASE + "/app/learn"],
  ["38-investor-dna", BASE + "/app/investor-dna"],
  ["39-be-the-company", BASE + "/app/be-the-company"],
  ["40-ai-tutor", BASE + "/app/tutor"],
  ["41-research-review", BASE + "/app/research-network"],
  ["42-data-status", BASE + "/app/data-sources"],
  ["43-settings", BASE + "/app/settings"],
  ["44-roadmap", BASE + "/app/capabilities"],
  ["45-help", BASE + "/app/help"],
  ["46-more", BASE + "/app/more"],
];

const only = process.argv.slice(2);
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});
const results = [];
if (!only.length) {
  // First-run onboarding is a feature in its own right: capture it, then dismiss it.
  const first = await context.newPage();
  await first.goto(BASE + "/app/dashboard");
  await first.waitForTimeout(5_000);
  await first.screenshot({ path: join(OUT, "09-onboarding-investor-dna.png") });
  await first.getByRole("button", { name: "Close welcome" }).click();
  await first.waitForTimeout(1_500);
  // Throwaway tour book only: add Rs 1,00,000 VIRTUAL cash so wallet/ledger pages are populated.
  await first.goto(BASE + "/app/wallet");
  await first.waitForTimeout(4_000);
  await first.getByRole("button", { name: "Add ₹1,00,000", exact: true }).click();
  await first.waitForTimeout(3_000);
  await first.close();
}
for (const [name, url] of pages) {
  if (only.length && !only.some((o) => name.includes(o))) continue;
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message).slice(0, 200)));
  let status = "ok";
  try {
    const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45_000 });
    await page
      .waitForLoadState("networkidle", { timeout: name.includes("stock") ? 25_000 : 12_000 })
      .catch(() => {});
    await page.waitForTimeout(name.includes("stock") ? 6_000 : 2_500);
    const welcome = page.getByRole("button", { name: "Close welcome" });
    if (await welcome.isVisible().catch(() => false)) {
      await welcome.click();
      await page.waitForTimeout(1_000);
    }
    status = `${res?.status() ?? "?"} → ${new URL(page.url()).pathname}`;
    await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: false });
    await page.screenshot({ path: join(OUT, `${name}.full.png`), fullPage: true });
  } catch (e) {
    status = "FAILED: " + String(e.message).split("\n")[0];
  }
  results.push({ name, url, status, errors });
  console.log(name.padEnd(30), status, errors.length ? `(${errors.length} page errors)` : "");
  await page.close();
}
await browser.close();
writeFileSync(
  join(HERE, `capture-log${only.length ? "-partial" : ""}.json`),
  JSON.stringify(results, null, 2),
);
