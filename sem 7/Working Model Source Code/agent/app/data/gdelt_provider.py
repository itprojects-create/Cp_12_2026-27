"""GDELT historical news provider: India-market tone headlines for old as_of dates.

Source: D:\\Model\\NEW DATA\\gdelt_india_news_2015_2021.csv (GDELT 2.0 GKG, 64K rows,
2015-02 -> 2016-04 partial extraction). Use when as_of falls inside coverage;
otherwise return [] (the live gnews path owns fresh dates). PIT: article timestamp
<= as_of, enforced per row. Tone: tone_v15 first field = average tone (float).

Company matching is substring on the organizations field via TICKER_COMPANY map.
Unknown tickers match on the alphabetic prefix (e.g. RELIANCE from RELIANCE.NS).
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from functools import lru_cache

from app.data.local_store import MODEL_DATA_DIR
from app.data.sanitize import sanitize

GDELT_PATH = os.environ.get("GDELT_PATH", os.path.join(
    MODEL_DATA_DIR, "NEW DATA", "gdelt_india_news_2015_2021.csv"))
GDELT_COVERAGE_END = "2016-05-01"  # extract ends 2016-04-01; beyond this use live gnews

TICKER_COMPANY = {
    "RELIANCE.NS": "reliance industries", "INFY.NS": "infosys", "HDFCBANK.NS": "hdfc bank",
    "TCS.NS": "tata consultancy", "ICICIBANK.NS": "icici bank", "SBIN.NS": "state bank",
    "TATAMOTORS.NS": "tata motors", "TITAN.NS": "titan", "SUNPHARMA.NS": "sun pharma",
    "LT.NS": "larsen", "AXISBANK.NS": "axis bank", "KOTAKBANK.NS": "kotak",
    "MARUTI.NS": "maruti", "ULTRACEMCO.NS": "ultratech", "NTPC.NS": "ntpc",
    "POWERGRID.NS": "power grid", "ONGC.NS": "ongc", "COALINDIA.NS": "coal india",
    "BHARTIARTL.NS": "bharti airtel", "HCLTECH.NS": "hcl", "WIPRO.NS": "wipro",
    "ASIANPAINT.NS": "asian paints", "BAJFINANCE.NS": "bajaj finance",
    "ADANIENT.NS": "adani enterprises", "EICHERMOT.NS": "eicher",
}

@lru_cache(maxsize=2)
def _load(path: str):
    import pandas as pd
    df = pd.read_csv(path, usecols=["date", "source", "doc_url", "organizations", "tone_v15"])
    df["ts"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d%H%M%S", utc=True, errors="coerce")
    df["tone"] = df["tone_v15"].astype(str).str.split(",").str[0].astype(float)
    return df.dropna(subset=["ts"])

def _query(instrument: str) -> str:
    if instrument in TICKER_COMPANY:
        return TICKER_COMPANY[instrument]
    return "".join(c for c in instrument.split(".")[0] if c.isalpha()).lower() or instrument.lower()

class GdeltNewsProvider:
    """Historical NewsProvider implementation over the local GDELT extract."""
    name = "gdelt-historical"

    def __init__(self, path: str = ""):
        self.path = path or GDELT_PATH

    def headlines(self, query: str, as_of: datetime, max_items: int = 10) -> list[dict]:
        import pandas as pd
        if not os.path.exists(self.path):
            return []
        au = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        df = _load(self.path)
        q = (TICKER_COMPANY.get(query, query) if "." in query else query).lower()
        hits = df[df["organizations"].str.lower().str.contains(q, na=False)]
        hits = hits[hits["ts"] <= au].sort_values("ts", ascending=False).head(max_items)
        out = []
        for _, r in hits.iterrows():
            out.append({"title": sanitize(
                            f"[{r['source']}] tone={r['tone']:+.2f} {str(r['organizations'])[:160]}", 300),
                        "publisher": sanitize(str(r["source"]), 120),
                        "published_at": pd.Timestamp(r["ts"]).isoformat(),
                        "url": str(r["doc_url"])[:300]})
        return out
