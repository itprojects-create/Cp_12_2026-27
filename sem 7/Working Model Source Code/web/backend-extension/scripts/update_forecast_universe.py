"""Refresh data/forecast_universe.json from the official NSE index constituent CSVs.

Usage (from backend-extension, offline-safe, no keys):
  python -B scripts/update_forecast_universe.py --out D:\QP\agent-service\data\forecast_universe.json

Membership is point-in-time: the file records retrieved_at and both index names.
Source of truth: NSE archives index constituent files (public CSV, no login).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone

import httpx

INDICES = {
    "NIFTY 50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY NEXT 50": "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "text/csv,*/*"}


def fetch(index: str, url: str) -> list[dict]:
    r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
    r.raise_for_status()
    first = r.text.splitlines()[0]
    if "<!DOCTYPE" in first.upper() or "<html" in first.lower():
        raise ValueError(f"{index}: response is HTML, not CSV")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    out = []
    for row in rows:
        symbol = (row.get("Symbol") or "").strip().upper()
        if symbol and (row.get("Series") or "EQ").strip() == "EQ":
            out.append({"symbol": symbol, "name": (row.get("Company Name") or "").strip(),
                        "sector": (row.get("Industry") or "Unknown").strip(), "index": index})
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/forecast_universe.json")
    args = parser.parse_args(argv)
    rows, failures = [], []
    for index, url in INDICES.items():
        try:
            rows.extend(fetch(index, url))
        except Exception as error:  # noqa: BLE001 - one index failing must not poison the file
            failures.append(f"{index}: {type(error).__name__}: {error}"[:200])
    seen: set[str] = set()
    merged = []
    for row in rows:
        if row["symbol"] not in seen:
            seen.add(row["symbol"])
            merged.append(row)
    payload = {
        "source": "https://archives.nseindia.com/content/indices/ (official NSE constituent CSVs)",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "indices": list(INDICES),
        "rows": merged,
        "failures": failures,
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(body)
    print(json.dumps({"symbols": len(merged), "failures": failures, "written": args.out}))


if __name__ == "__main__":
    main()
