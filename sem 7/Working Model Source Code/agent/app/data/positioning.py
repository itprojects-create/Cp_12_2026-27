"""Positioning veto inputs: delivery (archive, PIT-clean) + FII/PCR (best-effort).

Discipline: any leg that cannot be honestly computed ABSTAINS (contributes 0.0
with a flag) — never imputed, never defaulted to danger or safety. Combined
with the frozen veto by max() (veto-only preserved). Prereg §3.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

CACHE_PATH = "data/positioning_cache.json"
_NSE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _asof_date(as_of: datetime) -> str:
    a = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    return a.date().isoformat()


def fetch_nse_json(url: str, timeout: int = 10) -> dict | None:
    """Best-effort NSE fetch. ANY failure (network, shape, auth) -> None."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers=_NSE_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_fii_daily() -> dict | None:
    """Latest FII net cash (Rs cr). Shape-mismatch -> None (honest)."""
    data = fetch_nse_json("https://www.nseindia.com/api/fiidiiTradeReco")
    try:
        for row in data["data"]:
            if row.get("category") == "FII/FPI":
                buy = float(str(row.get("buyValue", 0)).replace(",", ""))
                sell = float(str(row.get("sellValue", 0)).replace(",", ""))
                return {"date": str(row.get("date", "")), "fii_net_cr": buy - sell}
        return None
    except Exception:
        return None


def fetch_nifty_pcr() -> dict | None:
    """NIFTY put/call OI ratio + timestamp. Failure -> None."""
    data = fetch_nse_json("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY")
    try:
        ce = float(data["filtered"]["CE"]["totOI"])
        pe = float(data["filtered"]["PE"]["totOI"])
        if ce <= 0:
            return None
        return {"date": data.get("records", {}).get("timestamp", "")[:10],
                "pcr": pe / ce}
    except Exception:
        return None


def update_cache(cache_path: str = CACHE_PATH, fii: dict | None = None,
                 pcr: dict | None = None) -> dict:
    """Idempotent per-date append of {date: {fii_net_cr, pcr}}. Returns cache."""
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8-sig") as f:
            cache = json.load(f)
    for entry, field in ((fii, "fii_net_cr"), (pcr, "pcr")):
        if entry and entry.get("date"):
            day = cache.setdefault(entry["date"][:10], {})
            if field in entry and entry[field] is not None:
                day[field] = float(entry[field])
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    return cache


def _trailing(cache: dict, before_date: str, field: str, n: int) -> list[float]:
    """Values strictly before before_date (PIT), most-recent-first, up to n."""
    days = sorted(d for d in cache if d < before_date and field in cache[d])
    return [float(cache[d][field]) for d in days[-n:]]


def positioning_veto_fraction(delivery_z: float | None, fii_neg: bool | None,
                               pcr_extreme: bool | None) -> tuple[float, list[str]]:
    """Pure veto table (prereg §3). None leg = abstain + flag. Returns (fraction, flags)."""
    flags: list[str] = []
    legs = 0
    if delivery_z is None:
        flags.append("delivery:unavailable")
    elif delivery_z <= -2.0:
        legs += 1
    if fii_neg is None or pcr_extreme is None:
        flags.append("fii-pcr:unavailable")
    elif fii_neg and pcr_extreme:
        legs += 1
    if legs >= 2:
        return 1.0, flags
    if legs == 1:
        return 0.5, flags
    return 0.0, flags


def positioning_at(ticker: str, as_of: datetime, delivery_store=None,
                   fii: dict | None = None, pcr: dict | None = None,
                   cache_path: str = CACHE_PATH,
                   fetch_live: bool = False) -> dict:
    """Assemble positioning veto inputs. fetch_live=True attempts NSE (may still
    return unavailable legs); default False = cache + delivery only (offline-safe).

    Default delivery source is the parquet panel (Amendment 1: proven canonical
    over the slim copy — internally consistent to 0.005pp with documented
    pipeline; slim diverges 7pp mean with unknown provenance).
    """
    from app.data.delivery_panel import ParquetDeliveryStore
    store = delivery_store or ParquetDeliveryStore()
    try:
        d = store.latest(ticker, as_of)
        z = d["z20"] if d else None
    except Exception:
        z, d = None, None
    if fetch_live:
        fii = fii or fetch_fii_daily()
        pcr = pcr or fetch_nifty_pcr()
        if fii or pcr:
            update_cache(cache_path, fii, pcr)
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8-sig") as f:
            cache = json.load(f)
    day = _asof_date(as_of)
    fii_5d = _trailing(cache, day, "fii_net_cr", 5)
    fii_neg = (sum(fii_5d) < 0) if len(fii_5d) == 5 else None
    pcr_now = (pcr or {}).get("pcr")
    hist = _trailing(cache, day, "pcr", 60)
    if pcr_now is None and hist:
        pcr_now = hist[-1]  # latest cached snapshot strictly before as_of
    pcr_extreme = ((sum(1 for v in hist if v < pcr_now) / len(hist) * 100 >= 90)
                   if pcr_now is not None and len(hist) >= 20 else None)
    veto, flags = positioning_veto_fraction(z, fii_neg, pcr_extreme)
    if d is None:
        flags = ["delivery:unavailable"] + flags
    return {"delivery_z": z, "fii_net_5d": sum(fii_5d) if fii_5d else None,
            "pcr": pcr_now, "veto": veto, "flags": flags,
            "data_status": "DATA_OK" if veto > 0 or not flags else "DATA_UNAVAILABLE"}
