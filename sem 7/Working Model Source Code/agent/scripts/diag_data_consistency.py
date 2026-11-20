"""Consistency diagnostics: slim-vs-parquet delivery + local-vs-yahoo VIX regime.

Prereg_model_data_wiring: delivery swap needs flag concordance reported;
VIX swap needs >=99% regime agreement or it is blocked (investigate, average).
Deterministic except the yfinance leg (read-only fetch). Zero LLM tokens.
Writes data/diag_data_consistency.json (evidence, not a claim).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def delivery_concordance(sample_tickers: list[str], sample_dates: list[str]) -> dict:
    from app.data.local_store import DeliveryStore
    from app.data.delivery_panel import ParquetDeliveryStore
    slim, parq = DeliveryStore(), ParquetDeliveryStore()
    agree = flags = slim_none = parq_none = 0
    for t in sample_tickers:
        for d in sample_dates:
            as_of = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
            try:
                a = slim.latest(t, as_of)
            except Exception:
                a = None
            try:
                b = parq.latest(t, as_of)
            except Exception:
                b = None
            if a is None:
                slim_none += 1
            if b is None:
                parq_none += 1
            if a is None or b is None:
                continue
            fa = "acc" if (a["z20"] or 0) >= 1.0 else ("dist" if (a["z20"] or 0) <= -1.0 else "neu")
            fb = "acc" if (b["z20"] or 0) >= 1.0 else ("dist" if (b["z20"] or 0) <= -1.0 else "neu")
            flags += 1
            agree += fa == fb
    return {"tickers": len(sample_tickers), "dates": len(sample_dates),
            "comparable": flags, "agree": agree,
            "concordance": round(agree / flags, 4) if flags else None,
            "slim_none": slim_none, "parquet_none": parq_none}


def vix_regime_agreement(dates: list[str]) -> dict:
    import pandas as pd
    from app.data.regime import classify_regime
    from app.data import vix_local
    from app.data.yfinance_provider import YFinanceProvider
    agree = total = yf_fail = 0
    for d in dates:
        as_of = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
        try:
            df = YFinanceProvider().ohlcv("^INDIAVIX", as_of, "1d", lookback=400)
            yf_reg = classify_regime(df["Close"].dropna(), len(df) - 1)
        except Exception:
            yf_fail += 1
            continue
        hist = vix_local.history(as_of)
        if not hist:
            continue
        local_reg = classify_regime(pd.Series(hist), len(hist) - 1)
        total += 1
        agree += yf_reg == local_reg
    return {"dates": len(dates), "comparable": total,
            "agree": agree, "agreement": round(agree / total, 4) if total else None,
            "yfinance_failures": yf_fail,
            "swap_allowed_99pct": (agree / total >= 0.99) if total else False}


def main() -> None:
    tickers = ["RELIANCE.NS", "INFY.NS", "HDFCBANK.NS", "TCS.NS", "SBIN.NS",
               "ITC.NS", "LT.NS", "AXISBANK.NS"]
    month_ends = [f"{y}-{m:02d}-28" for y in (2022, 2023, 2024, 2025) for m in (3, 6, 9, 12)]
    out = {
        "delivery": delivery_concordance(tickers, month_ends),
        "vix_regime": vix_regime_agreement([d + "T15:30:00+00:00" for d in month_ends]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join("data", "diag_data_consistency.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("report:", path)


if __name__ == "__main__":
    main()
