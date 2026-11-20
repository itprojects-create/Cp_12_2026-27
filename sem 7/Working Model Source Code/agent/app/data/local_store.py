"""Local PIT stores backed by audited Model datasets (self-contained copies under data/).

- data/delivery_features.csv: NSE MTO delivery %, generated from the quant-plus
  v3 feature build (slim: date,ticker,delivery_pct,ma5,z20). Real archive data.
- PIT rule (matches the Model causality tests): the delivery file publishes
  post-close, so a decision stamped as_of may use the latest row STRICTLY BEFORE
  as_of's date (1-session lag). Never same-day.
- Missing file/ticker/date -> None (caller abstains, never fabricates).

Deliberately NOT wired: multi_factor_regimes.csv — checked 2010-2025: its HMM
states {0,1} do not separate forward-20d returns (1.008% vs 0.970%) or realized
vol (corr 0.027). Injecting uninterpretable states as 'bull/bear' would be fake
signal, so it stays out until semantics are proven.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data")
MODEL_DATA_DIR = os.environ.get("MODEL_DATA_DIR", r"D:\Model")

def _asof_date(as_of: datetime) -> str:
    a = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    return a.date().isoformat()

@lru_cache(maxsize=4)
def _load_csv(path: str):
    import pandas as pd
    return pd.read_csv(path)

class DeliveryStore:
    """NSE delivery % with 1-session-lag PIT rule.

    DEPRECATED for new code (Amendment 1, prereg_model_data_wiring.md): the slim
    copy diverges 7.0pp mean from the internally-consistent parquet panel with
    unknown provenance. Behavior FROZEN for existing callers (Technical analyst
    keeps it pending its own prompt-input prereg). New paths: ParquetDeliveryStore.
    """
    def __init__(self, path: str = ""):
        self.path = path or os.path.join(DATA_DIR, "delivery_features.csv")

    def latest(self, ticker: str, as_of: datetime) -> dict | None:
        if not os.path.exists(self.path):
            return None
        df = _load_csv(self.path)
        sub = df[(df["ticker"] == ticker) & (df["date"] < _asof_date(as_of))]
        if sub.empty:
            return None
        row = sub.iloc[-1]
        import math
        z = row["delivery_pct_z20"]
        z = None if (z is None or (isinstance(z, float) and math.isnan(z))) else float(z)
        return {"date": str(row["date"]), "delivery_pct": float(row["delivery_pct"]),
                "ma5": float(row["delivery_pct_ma5"]), "z20": z}

    def line(self, ticker: str, as_of: datetime) -> str:
        d = self.latest(ticker, as_of)
        if not d:
            return "delivery: unavailable (no archive row before as_of)"
        z = f"{d['z20']:+.2f}" if d["z20"] is not None else "n/a"
        flag = ("accumulation" if (d["z20"] or 0) >= 1.0 else
                "distribution" if (d["z20"] or 0) <= -1.0 else "neutral")
        return (f"delivery[{d['date']}, 1-session lag]: pct={d['delivery_pct']:.1f}% "
                f"ma5={d['ma5']:.1f}% z20={z} -> {flag}")
