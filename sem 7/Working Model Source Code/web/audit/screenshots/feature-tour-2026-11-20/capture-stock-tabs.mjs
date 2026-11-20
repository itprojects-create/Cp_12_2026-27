// Extra stock-workspace views: order ticket, Research (AI + news sentiment) tab, Decision plan.
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "shots");
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
await p.goto("http://127.0.0.1:4180/app/stocks/RELIANCE");
await p.waitForTimeout(8000);
const close = p.getByRole("button", { name: "Close welcome" });
if (await close.isVisible().catch(() => false)) await close.click();
await p.getByRole("button", { name: /^Buy/ }).first().click();
await p.waitForTimeout(2500);
await p.screenshot({ path: join(OUT, "12b-stock-order-ticket.png") });
await p.reload();
await p.waitForTimeout(8000);
for (const [tab, name] of [
  ["Research", "12c-stock-research-ai-sentiment"],
  ["Decision plan", "12d-stock-decision-plan"],
]) {
  await p.getByText(tab, { exact: true }).last().click();
  await p.waitForTimeout(12000);
  await p.screenshot({ path: join(OUT, `${name}.png`) });
  await p.screenshot({ path: join(OUT, `${name}.full.png`), fullPage: true });
}
await b.close();
console.log("done");
