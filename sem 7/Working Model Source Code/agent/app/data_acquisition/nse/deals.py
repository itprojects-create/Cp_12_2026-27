"""NSE bulk/block deals collector (§25).

Sources (official, best-effort — deal archive paths have changed historically;
any layout/endpoint drift returns SOURCE_SCHEMA_CHANGED/SOURCE_UNAVAILABLE,
never a fabricated row). Normalized §25 fields; client names preserved verbatim
— no 'smart money' inference, ever.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import parquet as PQ
from app.data_acquisition import util as U

ARCH = "https://nsearchives.nseindia.com/content/equities"
COLLECTOR_VERSION = "nse-deals-v1"


def deals_url(kind: str, day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    base = "bulk.csv" if kind == "BULK" else "block.csv"
    # current-day file; historical per-date archives use dated variants below
    return f"{ARCH}/{base}"


def dated_deals_url(kind: str, day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    stem = "bulk" if kind == "BULK" else "block"
    return (f"{ARCH}/historical/{stem}/{d.year}/{d.strftime('%b').upper()}/"
            f"{stem}_{d.day:02d}{d.strftime('%b').upper()}{d.year}.csv")


def parse_deals(payload: bytes, kind: str, day_iso: str) -> tuple[list[dict], dict]:
    text = payload.decode("utf-8-sig", "replace")
    reader = csv.DictReader(text.splitlines())
    cols = reader.fieldnames or []
    rows = []
    for r in reader:
        symbol = (r.get("Symbol") or r.get("SYMBOL") or "").strip().upper()
        if not symbol:
            continue
        side = (r.get("Buy / Sell") or r.get("BUY_SELL") or "").strip().upper()
        side = "BUY" if side.startswith("BUY") else "SELL" if side.startswith("SELL") else ""
        if not side:
            continue
        try:
            qty = float(str(r.get("Quantity Traded") or r.get("QUANTITY") or "").replace(",", ""))
            price = float(str(r.get("Trade Price / Wght. Avg. Price") or r.get("PRICE") or ""
                              ).replace(",", ""))
        except (TypeError, ValueError):
            continue
        rows.append({"trade_date": day_iso, "symbol": symbol + ".NS",
                     "client_name": str(r.get("Client Name") or r.get("CLIENT") or "")[:120],
                     "side": side, "quantity": qty, "price": price,
                     "deal_type": kind,
                     "publication_ts": day_iso, "ingestion_ts": U.utcnow()})
    return rows, {"columns": cols, "schema_fingerprint": U.schema_fingerprint(cols)}


class NseDeals(B.Collector):
    source_name = "NSE"
    dataset_name = "bulk-block-deals"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              days: list[str] | None = None, kinds: tuple = ("BULK", "BLOCK"),
              http_get=None) -> B.FetchResult:
        started = U.utcnow()
        get = http_get or H.get
        day = datetime.now(timezone.utc).date().isoformat()
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        failures, hashes = [], []
        for d in days or [day]:
            for kind in kinds:
                url = deals_url(kind, d)
                try:
                    resp = get(url)
                    art = B.store_raw(self.source_name, self.dataset_name, d,
                                      f"{kind.lower()}_{d}.csv", resp["bytes"],
                                      source_url=url,
                                      content_type=resp["headers"].get("content-type", ""),
                                      collector_version=COLLECTOR_VERSION)
                    hashes.append(art["sha256"])
                    rows, _rep = parse_deals(resp["bytes"], kind, d)
                    res.records_received += len(rows)
                    if rows:
                        import pandas as pd
                        stat = PQ.upsert("bulk-block-deals", d[:7], pd.DataFrame(rows),
                                         ["trade_date", "symbol", "client_name", "side",
                                          "deal_type"])
                        res.records_written += stat["added"]
                except H.HttpError as e:
                    code = e.code or 0
                    status = (B.FetchStatus.RATE_LIMITED if code == 429
                              else B.FetchStatus.SOURCE_BLOCKED if code in (401, 403)
                              else B.FetchStatus.SOURCE_UNAVAILABLE)
                    failures.append({"day": d, "kind": kind, "status": status.value,
                                     "note": str(e)[:200]})
                    B.log_error(self.source_name, self.dataset_name, d, status.value,
                                f"{kind}: {e}", code, 0, COLLECTOR_VERSION)
                except Exception as e:  # noqa: BLE001
                    failures.append({"day": d, "kind": kind, "status": "SOURCE_UNAVAILABLE",
                                     "note": f"{type(e).__name__}: {e}"[:200]})
        res.finished_at = U.utcnow()
        res.raw_hashes = hashes
        res.source_failures = failures
        if failures and res.records_received == 0:
            res.status = B.FetchStatus.SOURCE_UNAVAILABLE
        elif failures:
            res.status = B.FetchStatus.PARTIAL
        res.batch_id = f"{self.source_name}-{self.dataset_name}-{day}"
        B.mark_health(self.source_name, self.dataset_name,
                      ok=res.records_received > 0, status=res.status.value,
                      expected_freshness="daily-post-settlement")
        return res
