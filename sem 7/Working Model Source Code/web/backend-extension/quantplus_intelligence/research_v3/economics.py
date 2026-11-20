"""V3.1 fee adapter and versioned return metrics (W0.4).

Two jobs, per the V3.1 master prompt:

1. Integer-paise mirror of the tested web paper-book charge schedule
   (``src/lib/paper-fees.ts`` — schedule ``nse-cm-delivery-2026-03-01``), plus an
   optional date-versioned FYERS delivery-brokerage component documented as
   ``min(0.3% x order value, Rs 20)`` per executed order. All money is integer
   paise; rounding mirrors ``src/lib/money.ts`` exactly (round half away from
   zero; STT rounded to the nearest rupee per fill).

2. Versioned return metrics that keep three different numbers separate:

   ``v3_benchmark_relative``  stock gross return - benchmark gross return.
                              NOT investor cash P&L; cannot be displayed as profit.
   ``v3_trade_cash_pnl``      exact integer-paise sale proceeds - purchase cost -
                              all itemised charges for the round trip.
   ``v3_net_absolute``        v3_trade_cash_pnl / purchase turnover (fraction).

The V2 series in ``bridge.py``/``shadow.py`` (realised excess minus a flat 0.004)
is preserved untouched; this module provides the corrected, versioned V3 series
alongside it. Consumers must label the metric version in every report.
"""
from __future__ import annotations

import math
from typing import Literal

Side = Literal["BUY", "SELL"]

ScheduleUnavailable = "CHARGE_SCHEDULE_UNAVAILABLE"

# Date-versioned schedules. Only dates at/after effective_from are supported;
# unknown dates fail closed exactly like the web book does.
SCHEDULES: tuple[dict, ...] = (
    {
        "id": "nse-cm-delivery-2026-03-01",
        "effective_from": "2026-03-01",
        # STT 0.1% on buy and sell for delivery equity, rounded to the rupee per fill.
        "stt_delivery_rate": 0.001,
        # NSE Rs 306.99 + IPFT Rs 0.01 per crore each side (NSE/FA/73061) => Rs 307/cr.
        "exchange_rate": 307 / 1e7,
        # SEBI turnover fee Rs 10 per crore.
        "sebi_rate": 10 / 1e7,
        # Stamp duty 0.015% on delivery purchases only.
        "stamp_delivery_buy_rate": 0.00015,
        # GST 18% of brokerage + exchange + SEBI fee.
        "gst_rate": 0.18,
        "sources": ["NSE/FA/73061", "Finance Act STT schedule", "Indian Stamp Act 2019 amendment"],
    },
)

# Optional broker components, date-versioned. The tested paper book assumes a
# zero-brokerage delivery broker; FYERS delivery brokerage is documented as
# min(0.3% x order value, Rs 20) per executed order and is modelled here as an
# explicit, separately auditable component (not silently mixed into the book).
BROKER_COMPONENTS: dict[str, tuple[dict, ...]] = {
    "book_zero_brokerage": (
        {"id": "zero-brokerage-assumption", "effective_from": "2026-03-01",
         "delivery_brokerage": None, "dp_sell_paise": 0,
         "note": "paper book assumption: zero delivery brokerage, no DP debit"},
    ),
    "fyers_delivery_2026": (
        {"id": "fyers-delivery-min0.3pct-or-20", "effective_from": "2026-01-01",
         "delivery_brokerage": {"rate": 0.003, "cap_rupees": 20.0, "scope": "per_order"},
         "dp_sell_paise": 0,
         "note": "FYERS equity-delivery brokerage min(0.3% x order value, Rs 20) "
                 "per executed order; verify current schedule before live use (paper only)"},
    ),
}


def _apply_rate(amount_paise: int, rate: float) -> int:
    """Round half away from zero, identical to money.ts applyRate (Math.round semantics)."""
    value = amount_paise * rate
    return -math.floor(abs(value) + 0.5) if value < 0 else math.floor(value + 0.5)


def _round_to_rupee(amount_paise: int) -> int:
    """Round to the nearest whole rupee half-up, identical to money.ts roundToRupee."""
    return math.floor(amount_paise / 100 + 0.5) * 100


def charge_schedule(at_iso: str) -> dict:
    day = at_iso[:10]
    for schedule in sorted(SCHEDULES, key=lambda s: s["effective_from"], reverse=True):
        if schedule["effective_from"] <= day:
            return schedule
    raise ValueError(ScheduleUnavailable)


def broker_component(broker: str, at_iso: str) -> dict:
    day = at_iso[:10]
    for component in sorted(BROKER_COMPONENTS[broker], key=lambda c: c["effective_from"], reverse=True):
        if component["effective_from"] <= day:
            return component
    raise ValueError(ScheduleUnavailable)


def delivery_charges(side: Side, turnover_paise: int, at_iso: str,
                     *, broker: str = "book_zero_brokerage",
                     first_fill_of_order: bool = True) -> dict:
    """Itemised charges for one delivery fill; every amount is integer paise.

    Mirrors paper-fees.deliveryCharges with two additions: an explicit broker
    component key, and per-order brokerage (brokerage applies on the order's
    first fill only, matching the book's ``firstFillOfOrder`` semantics).
    """
    if not isinstance(turnover_paise, int) or turnover_paise <= 0:
        raise ValueError("turnover must be a positive integer of paise")
    schedule = charge_schedule(at_iso)
    broker_cfg = broker_component(broker, at_iso)  # validates broker/date pair
    stt = _round_to_rupee(_apply_rate(turnover_paise, schedule["stt_delivery_rate"]))
    exchange = _apply_rate(turnover_paise, schedule["exchange_rate"])
    sebi = _apply_rate(turnover_paise, schedule["sebi_rate"])
    items: list[dict] = [
        {"code": "STT", "amount_paise": stt, "basis": "0.1% of delivery turnover, rounded to the rupee per fill"},
        {"code": "EXCHANGE", "amount_paise": exchange, "basis": "Rs 307 per crore each side"},
        {"code": "SEBI", "amount_paise": sebi, "basis": "Rs 10 per crore"},
    ]
    if side == "BUY":
        items.append({"code": "STAMP", "amount_paise": _apply_rate(turnover_paise, schedule["stamp_delivery_buy_rate"]),
                      "basis": "0.015% of delivery purchase value"})
    brokerage_rule = broker_cfg["delivery_brokerage"]
    if brokerage_rule is not None and first_fill_of_order:
        order_rupees = turnover_paise / 100
        brokerage = _apply_rate(100, min(brokerage_rule["rate"] * order_rupees, brokerage_rule["cap_rupees"]))
        items.append({"code": "BROKERAGE", "amount_paise": brokerage,
                      "basis": "min(rate x order value, cap) per executed order: "
                               f"{brokerage_rule['rate']:.3%} capped at Rs {brokerage_rule['cap_rupees']}"})
    else:
        items.append({"code": "BROKERAGE", "amount_paise": 0, "basis": "assumed zero brokerage"})
    if side == "SELL" and first_fill_of_order:
        items.append({"code": "DP", "amount_paise": broker_cfg["dp_sell_paise"],
                      "basis": "per-ISIN/day debit assumption (0 unless configured)"})
    gst_base = sum(i["amount_paise"] for i in items if i["code"] in ("BROKERAGE", "EXCHANGE", "SEBI"))
    items.append({"code": "GST", "amount_paise": _apply_rate(gst_base, schedule["gst_rate"]),
                  "basis": "18% of brokerage, exchange charge and SEBI fee"})
    return {"schedule": schedule["id"], "broker_component": broker,
            "items": items, "total_paise": sum(i["amount_paise"] for i in items)}


def trade_cash_pnl(quantity: int, buy_price_paise: int, sell_price_paise: int,
                   buy_at_iso: str, sell_at_iso: str, *,
                   broker: str = "book_zero_brokerage") -> dict:
    """Exact integer-paise round-trip delivery trade accounting.

    v3_trade_cash_pnl = sale proceeds - purchase cost - all attributed charges.
    Negative when the trade loses cash, regardless of benchmark performance.
    """
    if quantity <= 0 or buy_price_paise <= 0 or sell_price_paise <= 0:
        raise ValueError("quantity and prices must be positive integers")
    buy_turnover = quantity * buy_price_paise
    sell_turnover = quantity * sell_price_paise
    buy_charges = delivery_charges("BUY", buy_turnover, buy_at_iso, broker=broker)
    # One executed BUY order + one executed SELL order; each side's first fill carries
    # per-order brokerage. Multiple fills are modelled by calling delivery_charges
    # directly with first_fill_of_order=False for subsequent fills.
    sell_charges = delivery_charges("SELL", sell_turnover, sell_at_iso, broker=broker)
    charges_total = buy_charges["total_paise"] + sell_charges["total_paise"]
    cash_pnl = sell_turnover - buy_turnover - charges_total
    return {
        "quantity": quantity,
        "buy_turnover_paise": buy_turnover,
        "sell_turnover_paise": sell_turnover,
        "buy_charges": buy_charges,
        "sell_charges": sell_charges,
        "charges_total_paise": charges_total,
        "v3_trade_cash_pnl_paise": cash_pnl,
        "v3_net_absolute": cash_pnl / buy_turnover,
        "metric_versions": {"cash_pnl": "v3_trade_cash_pnl", "net": "v3_net_absolute"},
        "claim": "absolute cash accounting; benchmark-relative figures are NOT included",
    }


def v3_benchmark_relative(stock_gross_return: float, benchmark_gross_return: float) -> float:
    """Stock gross return minus aligned benchmark gross return. NOT cash P&L."""
    return stock_gross_return - benchmark_gross_return


METRIC_SEMANTICS = {
    "v3_benchmark_relative": "excess return vs benchmark; never display as investor profit",
    "v3_net_absolute": "absolute net return of the trade after itemised charges",
    "v3_trade_cash_pnl": "absolute net cash P&L in integer paise after itemised charges",
    "v2_excess_minus_flat_cost (legacy bridge/shadow)": "benchmark-relative excess minus a "
    "flat 0.4% hurdle; research evidence, not executable cash P&L (flat hurdle ignores size)",
}
