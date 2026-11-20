# W6 forward data, rights and dated economics

## Real lane status

No market-data provider, candidate universe, corporate-action feed, benchmark TRI feed, broker
account plan or notification destination was approved. Therefore there are **0 real observations**
and no paper order. W5 official-event capture remains `NOT_CONFIGURED` with 0 captured rows; Jev and
Mercury-3 are OFF. Retrospective vendor bars are never restamped as contemporaneous.

## Public primary-source discovery on 2026-11-14

- FYERS pricing: Standard delivery `min(0.3% × executed order value, ₹20)`; Prime
  `min(0.3%, ₹15)`. The public page confirms current terms, not the operator's account plan.
- FYERS detailed charges: delivery STT 0.1% buy/sell; NSE 0.0030699%; NSE IPFT ₹0.01/crore;
  SEBI ₹10/crore; stamp 0.015% on buy; GST 18% on the stated base; DP ₹12.50 + GST per scrip.
- FYERS DP support result: once per stock/ISIN per day regardless of sell-order count.
- FYERS 30 Sep 2024 notice: from 1 Oct 2024 delivery brokerage became 0.3%/₹20, DP was then
  reduced to ₹3.50, and NSE cash changed 0.003220%→0.002970%. This reconstructs only those named
  components; it is **not** a complete historical schedule and cannot bridge later changes.
- NSE corporate-actions page timed out. A webpage is not unrestricted capture/redistribution
  permission; automation remains disabled.

The current FYERS Standard/Prime components are coded as **observed from 2026-11-14 forward only**;
pre-observation dates fail closed. Real eligible economics remain `DATA_BLOCKED` until the operator
confirms the account plan and supplies an approved action/benchmark/feed path. Source registry:
`{"fyers_charges_list": {"accessed": "2026-11-14", "content_hash_status": "response_not_archived; facts quoted in W6 rights report", "status": "RESOLVED_PRIMARY_PAGE", "url": "https://fyers.in/charges-list"}, "fyers_dp_kb": {"accessed": "2026-11-14", "semantics": "Rs12.50+GST once per ISIN per day on delivery sells", "status": "PRIMARY_URL_TEXT_DISCOVERED_VIA_SEARCH_INDEX", "url": "https://support.fyers.in/portal/en/kb/articles/how-are-dp-charges-levied-in-fyers"}, "fyers_oct2024_notice": {"accessed": "2026-11-14", "historical_use": "brokerage/exchange/DP component context only; not a complete schedule", "status": "RESOLVED_HISTORICAL_CONTEXT_ONLY", "url": "https://fyers.in/notice-board/revision-of-brokerage-mtf-interest-and-other-charges-effective-october-1-2024"}, "fyers_pricing": {"accessed": "2026-11-14", "content_hash_status": "response_not_archived; facts quoted in W6 rights report", "status": "RESOLVED_PRIMARY_PAGE", "url": "https://fyers.in/pricing"}, "nse_corporate_actions": {"accessed": "2026-11-14", "status": "TIMED_OUT", "url": "https://www.nseindia.com/companies-listing/corporate-filings-actions"}}`.
