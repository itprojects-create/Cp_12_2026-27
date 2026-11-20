/**
 * W0.4 fee parity harness: prints the real web-book delivery charges (paper-fees.ts)
 * for fixed fixtures so the Python research_v3.economics mirror can be reconciled
 * paise-for-paise against the tested source of truth. Read-only; no account state.
 * Run: bun backend-extension/scripts/fee_parity_bun.ts
 */
import { deliveryCharges } from "../../src/lib/paper-fees.ts";

const cases = [
  { side: "BUY", turnover: 1_00_00_00, atIso: "2026-03-01T10:00:00Z" }, // Rs 10,000
  { side: "SELL", turnover: 1_00_00_00, atIso: "2026-03-01T10:00:00Z" },
  { side: "BUY", turnover: 10_00_00_00, atIso: "2026-03-01T10:00:00Z" }, // Rs 1,00,000
  { side: "SELL", turnover: 10_00_00_00, atIso: "2026-03-01T10:00:00Z" },
  { side: "BUY", turnover: 5_00_00_00, atIso: "2026-03-01T10:00:00Z" }, // Rs 50,000 (half fill)
  { side: "BUY", turnover: 10_00_00_00, atIso: "2026-02-28T10:00:00Z" }, // before effective date -> throws
];

const out = cases.map((c) => {
  try {
    const breakdown = deliveryCharges(c.side as "BUY" | "SELL", c.turnover, c.atIso);
    return {
      side: c.side,
      turnover_paise: c.turnover,
      at: c.atIso,
      schedule: breakdown.schedule,
      items: Object.fromEntries(breakdown.items.map((i) => [i.code, i.amount_paise])),
      total_paise: breakdown.total_paise,
    };
  } catch (error) {
    return {
      side: c.side,
      turnover_paise: c.turnover,
      at: c.atIso,
      error: String(error).replace(/"/g, ""),
    };
  }
});

console.log(JSON.stringify(out, null, 2));
