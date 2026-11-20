"""Canonical delivery panel from NSE MTO parquet (prereg_model_data_wiring.md Step 2a).

Same interface as local_store.DeliveryStore (latest/line) so callers swap
without logic changes. Differences (all deliberate, all disclosed):
- ALL symbols (2,300+/yr), not the 49-ticker slim copy.
- T+1 lag enforced: latest row STRICTLY BEFORE as_of date (NSE publishes post-close).
- ma5/z20 computed trailing-only on lagged rows: ma5 = mean(last 5 pct);
  z20 = (last - mean(last 20)) / sample_std(last 20, ddof=1); std==0 -> None.
  (Slim copy's z convention is unknown — consistency diagnostic compares FLAG
  concordance, never exact z equality.)
- Missing dir/file/symbol/date -> None (caller abstains) EXCEPT a missing
  panel dir itself, which raises (no silent empty universe of delivery data).
- Symbol mapping: ticker minus '.NS', verbatim (matches nifty500.txt: M&M.NS).
"""
from __future__ import annotations

import glob
import math
import os
from datetime import datetime, timezone
from functools import lru_cache

DEFAULT_PANEL_DIR = (
    os.environ.get("DELIVERY_PARQUET_DIR")
    or r"D:\Model\data\raw\delivery"
)


def _asof_date(as_of: datetime) -> str:
    a = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    return a.date().isoformat()


def _panel_files(panel_dir: str) -> list[str]:
    files = sorted(glob.glob(os.path.join(panel_dir, "delivery_*.parquet")))
    if not files:
        raise FileNotFoundError(
            f"delivery panel empty/missing: {panel_dir} — no silent fallback.")
    return files


@lru_cache(maxsize=1024)
def _symbol_frame(panel_dir: str, symbol: str):
    """All lagged rows for one symbol (pd DataFrame, date-ascending)."""
    import pandas as pd
    frames = []
    for path in _panel_files(panel_dir):
        try:
            df = pd.read_parquet(path, filters=[("symbol", "=", symbol)],
                                 columns=["date", "delivery_pct"])
        except Exception:
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        return None
    full = pd.concat(frames, ignore_index=True)
    full["date"] = pd.to_datetime(full["date"]).dt.strftime("%Y-%m-%d")
    return full.sort_values("date").reset_index(drop=True)


class ParquetDeliveryStore:
    """NSE delivery % with T+1-lag PIT rule (all symbols)."""

    def __init__(self, panel_dir: str = ""):
        self.panel_dir = panel_dir or DEFAULT_PANEL_DIR

    def latest(self, ticker: str, as_of: datetime) -> dict | None:
        symbol = ticker.upper().removesuffix(".NS")
        try:
            df = _symbol_frame(self.panel_dir, symbol)
        except FileNotFoundError:
            raise
        except Exception:
            return None
        if df is None or df.empty:
            return None
        sub = df[df["date"] < _asof_date(as_of)]
        if sub.empty:
            return None
        pct = sub["delivery_pct"].astype(float)
        last = float(pct.iloc[-1])
        ma5 = float(pct.tail(5).mean())
        z = None
        if len(pct) >= 20:
            w = pct.tail(20)
            sd = float(w.std(ddof=1))
            if sd > 0 and not math.isnan(sd):
                z = (last - float(w.mean())) / sd
        return {"date": str(sub["date"].iloc[-1]), "delivery_pct": last,
                "ma5": ma5, "z20": z}

    def line(self, ticker: str, as_of: datetime) -> str:
        d = self.latest(ticker, as_of)
        if not d:
            return "delivery: unavailable (no archive row before as_of)"
        z = f"{d['z20']:+.2f}" if d["z20"] is not None else "n/a"
        flag = ("accumulation" if (d["z20"] or 0) >= 1.0 else
                "distribution" if (d["z20"] or 0) <= -1.0 else "neutral")
        return (f"delivery[{d['date']}, 1-session lag]: pct={d['delivery_pct']:.1f}% "
                f"ma5={d['ma5']:.1f}% z20={z} -> {flag}")
