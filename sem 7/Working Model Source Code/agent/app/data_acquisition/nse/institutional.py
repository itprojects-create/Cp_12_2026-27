"""NSE FII/DII provisional flows collector (§26).

Source: official fiidiiTradeReco API (same endpoint the positioning provider
already reads — now with raw-first artifacts + registry discipline). Status is
always PROVISIONAL here; CDSL finals live in a separate dataset (§27) and are
never merged over provisionals.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import parquet as PQ
from app.data_acquisition import util as U

API = "https://www.nseindia.com/api/fiidiiTradeReco"
COLLECTOR_VERSION = "nse-flows-v1"


def parse_flows(payload: bytes, day_iso: str) -> tuple[list[dict], dict]:
    doc = json.loads(payload.decode("utf-8", "replace"))
    rows = []
    for r in doc if isinstance(doc, list) else doc.get("data", doc.get("rows", [])):
        cat = str(r.get("category") or r.get("Category") or "").strip().upper()
        if cat not in ("FII", "DII", "FPI"):
            continue

        def num(*ks):
            for k in ks:
                try:
                    if r.get(k) not in (None, ""):
                        return float(str(r[k]).replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return None

        buy = num("buyValue", "Buy", "buy")
        sell = num("sellValue", "Sell", "sell")
        net = num("netValue", "Net", "net")
        if buy is None and sell is None and net is None:
            continue
        rows.append({"date": day_iso, "category": cat, "buy_cr": buy, "sell_cr": sell,
                     "net_cr": net if net is not None
                     else (buy - sell if buy is not None and sell is not None else None),
                     "status": "PROVISIONAL"})
    return rows, {"n": len(rows)}


class NseFlows(B.Collector):
    source_name = "NSE"
    dataset_name = "fii-dii-provisional"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              day: str | None = None, http_get=None) -> B.FetchResult:
        started = U.utcnow()
        get = http_get or H.get
        day = day or datetime.now(timezone.utc).date().isoformat()
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        try:
            resp = get(API)
            art = B.store_raw(self.source_name, self.dataset_name, day, "flows.json",
                              resp["bytes"], source_url=API,
                              content_type="application/json",
                              collector_version=COLLECTOR_VERSION)
            res.raw_hashes = [art["sha256"]]
            try:
                rows, _rep = parse_flows(resp["bytes"], day)
            except ValueError:
                res.status = B.FetchStatus.SOURCE_SCHEMA_CHANGED
                res.source_failures = [{"status": "SOURCE_SCHEMA_CHANGED",
                                        "note": "unparseable flows payload; raw preserved"}]
                B.log_error(self.source_name, self.dataset_name, day,
                            "SOURCE_SCHEMA_CHANGED", "unparseable payload", None, 0,
                            COLLECTOR_VERSION)
                res.finished_at = U.utcnow()
                return res
            res.records_received = len(rows)
            if rows:
                import pandas as pd
                stat = PQ.upsert("fii-dii-provisional", day[:7], pd.DataFrame(rows),
                                 ["date", "category"])
                res.records_written = stat["added"]
            else:
                res.status = B.FetchStatus.NO_DATA
        except H.HttpError as e:
            code = e.code or 0
            status = (B.FetchStatus.RATE_LIMITED if code == 429
                      else B.FetchStatus.SOURCE_BLOCKED if code in (401, 403)
                      else B.FetchStatus.SOURCE_UNAVAILABLE)
            res.status = status
            res.source_failures = [{"status": status.value, "note": str(e)[:200]}]
            B.log_error(self.source_name, self.dataset_name, day, status.value,
                        str(e), code, 0, COLLECTOR_VERSION)
        except Exception as e:  # noqa: BLE001
            res.status = B.FetchStatus.SOURCE_UNAVAILABLE
            res.source_failures = [{"status": "SOURCE_UNAVAILABLE", "note": str(e)[:200]}]
        res.finished_at = U.utcnow()
        res.batch_id = f"{self.source_name}-{self.dataset_name}-{day}"
        B.mark_health(self.source_name, self.dataset_name,
                      ok=res.records_received > 0, status=res.status.value,
                      expected_freshness="daily-post-settlement")
        return res
