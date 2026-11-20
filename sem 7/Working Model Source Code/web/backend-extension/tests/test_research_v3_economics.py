"""W0.4 tests: absolute P&L vs benchmark-relative excess, and integer-paise fee truth.

The canonical fixture (master prompt W0.4):

    stock gross return   -5.00%
    index gross return   -6.00%
    relative advantage   +1.00 percentage point
    net absolute return  below -5.00% when trading costs are positive

The V2 bridge/shadow metric (realised excess - 0.004 flat) must never be displayed
as investor cash profit; research_v3.economics provides the corrected versioned
metrics. Fee expectations are cross-checked against the real TypeScript book engine
(src/lib/paper-fees.ts) via bun when bun is available (parity test skips otherwise).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quantplus_intelligence.research_v3 import economics
from quantplus_intelligence.research_v3.economics import (
    delivery_charges,
    trade_cash_pnl,
    v3_benchmark_relative,
)

REPO = Path(__file__).resolve().parents[2]
BUN_SCRIPT = REPO / "backend-extension" / "scripts" / "fee_parity_bun.ts"
BUN = shutil.which("bun")


def test_negative_absolute_return_not_profitable_from_index_excess():
    """+1pp benchmark-relative advantage with positive costs is a cash LOSS, not profit."""
    stock_ret, bench_ret = -0.05, -0.06
    relative = v3_benchmark_relative(stock_ret, bench_ret)
    assert relative == pytest.approx(0.01)          # the flattering number

    # Rs 1,000 x 100 shares bought, sold at Rs 950: stock return -5%.
    trade = trade_cash_pnl(quantity=100, buy_price_paise=100_000, sell_price_paise=95_000,
                           buy_at_iso="2026-11-02T10:00:00Z", sell_at_iso="2026-11-06T10:00:00Z")
    # Legacy V2 metric would have claimed: -0.05 - 0.004 relative-hurdle arithmetic
    # is meaningless as cash; with a +1pp excess the old "net" could read positive.
    legacy_flattering = (stock_ret - bench_ret) - 0.004
    assert legacy_flattering > 0                    # what the V2 formula shows
    assert trade["v3_trade_cash_pnl_paise"] < 0     # what the investor actually has
    assert trade["v3_net_absolute"] < stock_ret     # costs push net below gross
    assert trade["v3_net_absolute"] < -0.05
    # Relative advantage stays +1pp; cash P&L is -Rs 5,217.30 (paise -521730).
    assert trade["v3_trade_cash_pnl_paise"] == -521_730
    assert relative > 0 > trade["v3_trade_cash_pnl_paise"]


def test_fee_paissa_reconciliation_by_size_side_and_date():
    """Exact paise by notional, side, multi-fill and schedule effective-date boundary."""
    # Rs 10,000 turnover (1,000,000 paise) BUY, zero-brokerage book schedule.
    small_buy = delivery_charges("BUY", 1_000_000, "2026-03-01T10:00:00Z")
    assert {i["code"]: i["amount_paise"] for i in small_buy["items"]} == {
        "STT": 1000, "EXCHANGE": 31, "SEBI": 1, "STAMP": 150, "BROKERAGE": 0, "GST": 6,
    }
    assert small_buy["total_paise"] == 1188
    small_sell = delivery_charges("SELL", 1_000_000, "2026-03-01T10:00:00Z")
    assert small_sell["total_paise"] == 1038        # no stamp duty on sells

    # Rs 1,00,000 turnover BUY (matches engine.test.ts in the web book).
    lakh_buy = delivery_charges("BUY", 10_000_000, "2026-03-01T10:00:00Z")
    assert {i["code"]: i["amount_paise"] for i in lakh_buy["items"]} == {
        "STT": 10000, "EXCHANGE": 307, "SEBI": 10, "STAMP": 1500, "BROKERAGE": 0, "GST": 57,
    }
    assert lakh_buy["total_paise"] == 11874

    # Costs are size-dependent: 0.4% flat hurdle is not the executable schedule.
    small_rt = small_buy["total_paise"] + small_sell["total_paise"]
    lakh_rt = lakh_buy["total_paise"] + delivery_charges("SELL", 10_000_000, "2026-03-01T10:00:00Z")["total_paise"]
    assert lakh_rt == 22_248
    assert small_rt / 1_000_000 != lakh_rt / 10_000_000   # different fraction per size

    # Multi-execution: two Rs 50,000 fills of one order (brokerage applies on first fill).
    half = delivery_charges("BUY", 5_000_000, "2026-03-01T10:00:00Z")
    second = delivery_charges("BUY", 5_000_000, "2026-03-01T10:00:00Z", first_fill_of_order=False)
    assert {i["code"]: i["amount_paise"] for i in half["items"]} == {
        "STT": 5000, "EXCHANGE": 154, "SEBI": 5, "STAMP": 750, "BROKERAGE": 0, "GST": 29,
    }
    assert half["total_paise"] == 5938
    assert half["total_paise"] + second["total_paise"] == 11_876 != lakh_buy["total_paise"]

    # Schedule effective-date boundary: before 2026-03-01 fails closed.
    with pytest.raises(ValueError, match="CHARGE_SCHEDULE_UNAVAILABLE"):
        delivery_charges("BUY", 10_000_000, "2026-02-28T10:00:00Z")


def test_fyers_brokerage_component_min_rate_or_cap():
    """Documented FYERS delivery brokerage min(0.3% x value, Rs 20) per executed order."""
    # Rs 10,000 order: 0.3% = Rs 30 > Rs 20 cap -> Rs 20 = 2000 paise.
    fyers_small = delivery_charges("BUY", 1_000_000, "2026-03-01T10:00:00Z",
                                   broker="fyers_delivery_2026")
    brokerage = next(i for i in fyers_small["items"] if i["code"] == "BROKERAGE")
    assert brokerage["amount_paise"] == 2000
    # Rs 5,000 order: 0.3% = Rs 15 < cap -> Rs 15 = 1500 paise.
    tiny = delivery_charges("BUY", 500_000, "2026-03-01T10:00:00Z",
                            broker="fyers_delivery_2026")
    assert next(i for i in tiny["items"] if i["code"] == "BROKERAGE")["amount_paise"] == 1500
    # Second fill of the same order carries no brokerage again.
    fill2 = delivery_charges("BUY", 500_000, "2026-03-01T10:00:00Z",
                             broker="fyers_delivery_2026", first_fill_of_order=False)
    assert next(i for i in fill2["items"] if i["code"] == "BROKERAGE")["amount_paise"] == 0
    # GST is charged on brokerage too (18% of brokerage+exchange+sebi).
    assert fyers_small["items"][-1]["code"] == "GST"


def test_metric_semantics_are_declared():
    """Every V3 metric carries a non-negotiable honesty label."""
    assert "NEVER" in economics.METRIC_SEMANTICS["v3_benchmark_relative"].upper()
    assert "cash" in economics.METRIC_SEMANTICS["v3_trade_cash_pnl"]


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_python_fee_mirror_matches_typescript_book_engine():
    """Reconcile paise-for-paise against src/lib/paper-fees.ts via bun."""
    proc = subprocess.run([BUN, str(BUN_SCRIPT)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    expected = json.loads(proc.stdout)
    for case in expected:
        if "error" in case:
            with pytest.raises(ValueError, match="CHARGE_SCHEDULE_UNAVAILABLE"):
                delivery_charges(case["side"], case["turnover_paise"], case["at"])
            continue
        got = delivery_charges(case["side"], case["turnover_paise"], case["at"])
        got_items = {i["code"]: i["amount_paise"] for i in got["items"]}
        assert got_items == case["items"], case
        assert got["total_paise"] == case["total_paise"], case
        assert got["schedule"] == case["schedule"], case
