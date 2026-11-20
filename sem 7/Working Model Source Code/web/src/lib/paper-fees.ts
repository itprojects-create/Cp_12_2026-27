import { applyRate, roundToRupee, type Paise } from "./money.ts";

/**
 * Versioned NSE cash-market delivery charge schedule. Statutory, exchange and
 * broker assumptions are kept separate so each can be revised independently.
 * Sources and hashes: audit/implementation/reference-data.json.
 */
export type ChargeItem = {
  code: "STT" | "EXCHANGE" | "SEBI" | "STAMP" | "GST" | "BROKERAGE" | "DP" | "DP_GST";
  label: string;
  category: "STATUTORY" | "EXCHANGE" | "REGULATOR" | "BROKER_ASSUMPTION";
  amount_paise: Paise;
  basis: string;
};

export type ChargeBreakdown = {
  schedule: string;
  items: ChargeItem[];
  total_paise: Paise;
};

type Schedule = {
  id: string;
  effective_from: string;
  stt_delivery_rate: number;
  exchange_rate: number;
  sebi_rate: number;
  stamp_delivery_buy_rate: number;
  gst_rate: number;
  brokerage_paise_per_order: Paise;
  dp_paise_per_sell: Paise;
  sources: string[];
};

export const CHARGE_SCHEDULES: Schedule[] = [
  {
    id: "nse-cm-delivery-2026-03-01",
    effective_from: "2026-03-01",
    // 0.1% on buy and sell for delivery equity (unchanged by the April 2026 F&O revision).
    stt_delivery_rate: 0.001,
    // Rs 306.99 transaction charge + Rs 0.01 IPFT per crore each side (NSE/FA/73061).
    exchange_rate: 307 / 1e7,
    // SEBI turnover fee Rs 10 per crore.
    sebi_rate: 10 / 1e7,
    // Stamp duty 0.015% on delivery purchases.
    stamp_delivery_buy_rate: 0.00015,
    gst_rate: 0.18,
    // Broker assumptions: zero-brokerage delivery and no DP charge unless configured.
    brokerage_paise_per_order: 0,
    dp_paise_per_sell: 0,
    sources: ["NSE/FA/73061", "Finance Act STT schedule", "Indian Stamp Act 2019 amendment"],
  },
];

export function chargeSchedule(atIso: string): Schedule | null {
  const day = atIso.slice(0, 10);
  return (
    [...CHARGE_SCHEDULES]
      .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
      .find((schedule) => schedule.effective_from <= day) ?? null
  );
}

/** Itemised charges for one delivery fill. Unknown dates fail closed. */
export function deliveryCharges(
  side: "BUY" | "SELL",
  turnover: Paise,
  atIso: string,
  firstFillOfOrder = true,
): ChargeBreakdown {
  const schedule = chargeSchedule(atIso);
  if (!schedule) throw new Error("CHARGE_SCHEDULE_UNAVAILABLE");
  const brokerage = firstFillOfOrder ? schedule.brokerage_paise_per_order : 0;
  const exchange = applyRate(turnover, schedule.exchange_rate);
  const sebi = applyRate(turnover, schedule.sebi_rate);
  const items: ChargeItem[] = [
    {
      code: "STT",
      label: "Securities transaction tax",
      category: "STATUTORY",
      // STT is rounded to the nearest rupee; this applies the rounding per fill.
      amount_paise: roundToRupee(applyRate(turnover, schedule.stt_delivery_rate)),
      basis: "0.1% of delivery turnover, rounded to the rupee per fill",
    },
    {
      code: "EXCHANGE",
      label: "Exchange transaction charge",
      category: "EXCHANGE",
      amount_paise: exchange,
      basis: "Rs 307 per crore each side",
    },
    {
      code: "SEBI",
      label: "SEBI turnover fee",
      category: "REGULATOR",
      amount_paise: sebi,
      basis: "Rs 10 per crore",
    },
  ];
  if (side === "BUY")
    items.push({
      code: "STAMP",
      label: "Stamp duty",
      category: "STATUTORY",
      amount_paise: applyRate(turnover, schedule.stamp_delivery_buy_rate),
      basis: "0.015% of delivery purchase value",
    });
  items.push({
    code: "BROKERAGE",
    label: "Brokerage",
    category: "BROKER_ASSUMPTION",
    amount_paise: brokerage,
    basis: "Assumed zero-brokerage delivery",
  });
  if (side === "SELL" && firstFillOfOrder)
    items.push({
      code: "DP",
      label: "Depository charge",
      category: "BROKER_ASSUMPTION",
      amount_paise: schedule.dp_paise_per_sell,
      basis: "Broker/depository assumption; not modelled unless configured",
    });
  items.push({
    code: "GST",
    label: "GST",
    category: "STATUTORY",
    amount_paise: applyRate(brokerage + exchange + sebi, schedule.gst_rate),
    basis: "18% of brokerage, exchange charge and SEBI fee",
  });
  return {
    schedule: schedule.id,
    items,
    total_paise: items.reduce((total, item) => total + item.amount_paise, 0),
  };
}

export type ForwardBrokerPlan =
  "fyers_standard_observed_2026_11_14" | "fyers_prime_observed_2026_11_14";

const FORWARD_BROKER_PLANS: Record<
  ForwardBrokerPlan,
  { effective_from: string; cap_paise: Paise; source_version: string }
> = {
  fyers_standard_observed_2026_11_14: {
    effective_from: "2026-11-14",
    cap_paise: 2_000,
    source_version: "fyers-pricing+charges-list-observed-2026-11-14",
  },
  fyers_prime_observed_2026_11_14: {
    effective_from: "2026-11-14",
    cap_paise: 1_500,
    source_version: "fyers-pricing-observed-2026-11-14",
  },
};

/**
 * Additive, forward-only broker-plan charges. The existing application book
 * continues to call `deliveryCharges` and is byte-for-byte unchanged in
 * semantics. Current webpages are not back-projected before 2026-11-14.
 */
export function forwardDeliveryCharges(
  side: "BUY" | "SELL",
  turnover: Paise,
  atIso: string,
  plan: ForwardBrokerPlan,
  firstFillOfOrder = true,
  dpDebitForIsinDay = true,
): ChargeBreakdown & { broker_plan: ForwardBrokerPlan; source_version: string } {
  const config = FORWARD_BROKER_PLANS[plan];
  if (!config || atIso.slice(0, 10) < config.effective_from)
    throw new Error("CHARGE_SCHEDULE_UNAVAILABLE");
  const base = deliveryCharges(side, turnover, atIso, firstFillOfOrder);
  const items = base.items.map((item) => ({ ...item }));
  const brokerageItem = items.find((item) => item.code === "BROKERAGE")!;
  const brokerage = firstFillOfOrder ? Math.min(applyRate(turnover, 0.003), config.cap_paise) : 0;
  brokerageItem.amount_paise = brokerage;
  brokerageItem.basis = `FYERS ${plan.includes("prime") ? "Prime" : "Standard"}: min(0.3% of executed order, cap)`;
  const gstItem = items.find((item) => item.code === "GST")!;
  const exchange = items.find((item) => item.code === "EXCHANGE")!.amount_paise;
  const sebi = items.find((item) => item.code === "SEBI")!.amount_paise;
  gstItem.amount_paise = applyRate(brokerage + exchange + sebi, 0.18);
  gstItem.basis = "18% of brokerage, exchange charge and SEBI fee";
  if (side === "SELL") {
    const dpItem = items.find((item) => item.code === "DP")!;
    dpItem.amount_paise = firstFillOfOrder && dpDebitForIsinDay ? 1_250 : 0;
    dpItem.basis = "FYERS observed Rs 12.50 once per ISIN/day on delivery sells";
    items.push({
      code: "DP_GST",
      label: "GST on depository charge",
      category: "STATUTORY",
      amount_paise: applyRate(dpItem.amount_paise, 0.18),
      basis: "18% GST on the DP debit",
    });
  }
  return {
    schedule: `${base.schedule}+${config.source_version}`,
    broker_plan: plan,
    source_version: config.source_version,
    items,
    total_paise: items.reduce((total, item) => total + item.amount_paise, 0),
  };
}
