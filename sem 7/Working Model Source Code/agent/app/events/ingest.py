"""Ingest: best-effort exchange fetch + deterministic local feed reader.

Network follows the positioning.py pattern: any failure returns [] (total
functions, never raise on fetch). The deterministic input for tests, backtests,
and audit is a local JSONL feed (data/announcements/*.jsonl) — one raw dict
per line: {source, symbol, title, timestamp}.
"""
from __future__ import annotations

import glob
import json


def fetch_nse_announcements(symbol: str, timeout_s: float = 20.0) -> list[dict]:
    """Best-effort live fetch. Exchange endpoints change often; on ANY failure
    (network, schema drift, auth) return [] — callers abstain, never impute."""
    try:
        import urllib.request
        url = ("https://www.nseindia.com/api/corporate-announcements"
               f"?index=equities&symbol={symbol.replace('.NS', '')}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        out = []
        for row in (data if isinstance(data, list) else data.get("rows", [])):
            out.append({"source": "NSE", "symbol": symbol,
                        "title": str(row.get("headline", row.get("title", ""))),
                        "timestamp": str(row.get("an_dt", row.get("date", "")))})
        return out
    except Exception:  # noqa: BLE001 - best-effort by contract
        return []


def read_local_feed(pattern: str = "data/announcements/*.jsonl") -> list[dict]:
    """Deterministic reader for committed/audit feed files."""
    rows: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def feed_files_present(pattern: str = "data/announcements/*.jsonl") -> bool:
    return bool(glob.glob(pattern))
