"""Date-versioned broker plan components for the W6 forward paper book.

Sources (public pricing pages, resolved 2026-11-14 by the W6 preflight; reading
a public page documents the components but grants no data redistribution
right, and the per-date validation gate below still fails closed):

- https://fyers.in/pricing            -> Standard Rs 20 or 0.3% per executed
  order (delivery, whichever is lower); Prime Rs 15 or 0.3% whichever is
  lower; Prime membership Rs 499/month or Rs 4,990/annum.
- https://fyers.in/charges-list       -> delivery STT 0.1% buy & sell;
  NSE exchange transaction 0.0030699% + NSE IPFT Rs 0.01/crore; SEBI turnover
  fee Rs 10/crore; GST 18% of (brokerage + exchange + clearing + SEBI + IPFT);
  stamp duty 0.015% on delivery buy value; DP debit Rs 12.50 + GST per scrip
  (Rs 3.50 CDSL + Rs 9.00 FYERS) on sell.
- https://fyers.in/notice-board/revision-of-brokerage-mtf-interest-and-other-
  charges-effective-october-1-2024    -> historical context only: on 2024-10-01
  delivery brokerage became 0.3%/Rs 20 and DP was reduced to Rs 3.50, and the
  NSE cash exchange fee changed 0.003220% -> 0.002970%.  The current page again
  shows DP Rs 12.50 per scrip and NSE cash 0.0030699%, so the 2024 notice must
  NOT be extrapolated into a complete historical schedule (dates in between are
  unverified and fail closed).

The current pages do not prove when every current component first changed.
Consequently the current Standard/Prime+DP observations are valid only from the
2026-11-14 observation forward; they are never back-projected into earlier
history. Any unknown date/plan raises CHARGE_SCHEDULE_UNAVAILABLE.
"""
from __future__ import annotations

FORWARD_BROKER_COMPONENTS: dict[str, tuple[dict, ...]] = {
    "book_zero_brokerage": (
        {"id": "zero-brokerage-assumption", "effective_from": "2026-03-01",
         "delivery_brokerage": None, "dp_debit_paise": 0,
         "dp_scope": "none",
         "note": "paper book assumption: zero delivery brokerage, no DP debit"},
    ),
    # FYERS Standard, observed prospectively on the two primary pages 2026-11-14.
    "fyers_standard_observed_2026_11_14": (
        {"id": "fyers-standard-observed-2026-11-14", "effective_from": "2026-11-14",
         "delivery_brokerage": {"rate": 0.003, "cap_rupees": 20.0, "scope": "per_executed_order"},
         "dp_debit_paise": 1250, "dp_gst_rate": 0.18, "dp_scope": "per_scrip_per_sell_day",
         "dp_basis": "Rs 12.50 + GST per scrip (Rs 3.50 CDSL + Rs 9.00 FYERS) on sell",
          "note": "observed on fyers.in pricing/charges-list 2026-11-14; never valid before observation"},
    ),
    # FYERS Prime, per https://fyers.in/pricing (2026-11-14). Membership itself
    # (Rs 499/month or Rs 4,990/annum) is an operator cost, not a per-trade fee.
    "fyers_prime_observed_2026_11_14": (
        {"id": "fyers-prime-observed-2026-11-14", "effective_from": "2026-11-14",
         "delivery_brokerage": {"rate": 0.003, "cap_rupees": 15.0, "scope": "per_executed_order"},
         "dp_debit_paise": 1250, "dp_gst_rate": 0.18, "dp_scope": "per_scrip_per_sell_day",
         "dp_basis": "Rs 12.50 + GST per scrip (Rs 3.50 CDSL + Rs 9.00 FYERS) on sell",
          "note": "observed on fyers.in/pricing 2026-11-14; never valid before observation"},
    ),
}

BROKER_PLAN_NOTES = {
    "fyers_standard_observed_2026_11_14": "Standard plan: Rs 20 or 0.3% per executed order "
                           "(delivery, whichever is lower); DP Rs 12.50+GST per scrip.",
    "fyers_prime_observed_2026_11_14": "Prime plan: Rs 15 or 0.3% per executed order (delivery, "
                        "whichever is lower); membership Rs 499/month is an "
                        "operator cost outside per-trade accounting; DP as Standard.",
    "book_zero_brokerage": "Continuity assumption used by W1-W5 fixtures; not a "
                           "verified broker plan.",
}

SOURCE_REGISTRY = {
    "fyers_pricing": {"url": "https://fyers.in/pricing",
                      "accessed": "2026-11-14", "status": "RESOLVED_PRIMARY_PAGE",
                      "content_hash_status": "response_not_archived; facts quoted in W6 rights report"},
    "fyers_charges_list": {"url": "https://fyers.in/charges-list",
                           "accessed": "2026-11-14", "status": "RESOLVED_PRIMARY_PAGE",
                           "content_hash_status": "response_not_archived; facts quoted in W6 rights report"},
    "fyers_oct2024_notice": {
        "url": "https://fyers.in/notice-board/revision-of-brokerage-mtf-interest-"
               "and-other-charges-effective-october-1-2024",
        "accessed": "2026-11-14", "status": "RESOLVED_HISTORICAL_CONTEXT_ONLY",
        "historical_use": "brokerage/exchange/DP component context only; not a complete schedule"},
    "fyers_dp_kb": {"url": "https://support.fyers.in/portal/en/kb/articles/"
                            "how-are-dp-charges-levied-in-fyers",
                     "accessed": "2026-11-14",
                     "status": "PRIMARY_URL_TEXT_DISCOVERED_VIA_SEARCH_INDEX",
                     "semantics": "Rs12.50+GST once per ISIN per day on delivery sells"},
    "nse_corporate_actions": {"url": "https://www.nseindia.com/companies-listing/"
                                     "corporate-filings-actions",
                              "accessed": "2026-11-14", "status": "TIMED_OUT"},
}


def broker_component(plan: str, at_iso: str) -> dict:
    """Date-versioned broker component; unknown date/plan fails closed."""
    if plan not in FORWARD_BROKER_COMPONENTS:
        raise ValueError("CHARGE_SCHEDULE_UNAVAILABLE: unknown broker plan " + plan)
    day = at_iso[:10]
    for component in sorted(FORWARD_BROKER_COMPONENTS[plan],
                            key=lambda c: c["effective_from"], reverse=True):
        if component["effective_from"] <= day:
            return component
    raise ValueError("CHARGE_SCHEDULE_UNAVAILABLE: no component effective on " + day)


# The forward book computes fees through the parity-tested
# research_v3.economics.delivery_charges so brokerage/GST stay on one code
# path.  The two FYERS forward plans are therefore ALSO expressed here in the
# exact economics component format and registered ADDITIVELY (new keys only;
# the tested W1-W5 components are never modified).
FORWARD_ECONOMICS_COMPONENTS: dict[str, tuple[dict, ...]] = {
    "fyers_standard_observed_2026_11_14": (
        {"id": "fyers-standard-observed-2026-11-14", "effective_from": "2026-11-14",
         "delivery_brokerage": {"rate": 0.003, "cap_rupees": 20.0,
                                "scope": "per_executed_order"},
         "dp_sell_paise": 0,
         "note": "FYERS Standard delivery brokerage min(0.3% x order value, "
                 "Rs 20) per executed order, verified on fyers.in/charges-list "
                 "2026-11-14; DP debit is added separately by the forward book"},
    ),
    "fyers_prime_observed_2026_11_14": (
        {"id": "fyers-prime-observed-2026-11-14", "effective_from": "2026-11-14",
         "delivery_brokerage": {"rate": 0.003, "cap_rupees": 15.0,
                                "scope": "per_executed_order"},
         "dp_sell_paise": 0,
         "note": "FYERS Prime delivery brokerage min(0.3% x order value, "
                 "Rs 15) per executed order, verified on fyers.in/pricing "
                 "2026-11-14; DP debit is added separately by the forward book"},
    ),
}

_REGISTERED = False


def register_forward_plans_into_economics() -> None:
    """Idempotently add forward plan components to the economics registry.

    Only NEW plan keys are added; every existing (parity-tested) component
    remains byte-identical, so W1-W5 fee behaviour is unchanged.
    """
    global _REGISTERED
    from quantplus_intelligence.research_v3 import economics
    for plan, components in FORWARD_ECONOMICS_COMPONENTS.items():
        if plan not in economics.BROKER_COMPONENTS:
            economics.BROKER_COMPONENTS[plan] = components
    _REGISTERED = True


def fee_gate(plan: str | None, at_iso: str, *, corporate_action_source_ready: bool,
             account_plan_confirmed: bool) -> dict:
    """Code-owned real-paper fee gate; fixtures may still exercise assumptions.

    A public pricing page establishes a prospective observed schedule, not the
    operator's actual account plan and not corporate-action completeness.
    """
    reasons: list[str] = []
    component = None
    if plan is None:
        reasons.append("BROKER_PLAN_NOT_SELECTED")
    else:
        try:
            component = broker_component(plan, at_iso)
        except (KeyError, ValueError) as exc:
            reasons.append(str(exc))
    if not account_plan_confirmed:
        reasons.append("OPERATOR_ACCOUNT_PLAN_NOT_CONFIRMED")
    if not corporate_action_source_ready:
        reasons.append("CORPORATE_ACTION_SOURCE_NOT_CONFIGURED")
    return {
        "status": "VERIFIED_FOR_ELIGIBLE_PAPER" if not reasons else "DATA_BLOCKED",
        "plan": plan, "component": component, "reasons": reasons,
        "fixture_calculation_allowed": component is not None,
        "historical_extrapolation_allowed": False,
    }
