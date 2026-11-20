"""NSE indices collector: NIFTY 50/500, sector indices, India VIX, TRI (§24).

Source: official ind_close_all_DDMMYYYY.csv archives (best-effort). TRI vs
price provenance retained per row (§24: never merged silently).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import parquet as PQ
from app.data_acquisition import util as U

ARCH = "https://nsearchives.nseindia.com/content/indices"
COLLECTOR_VERSION = "nse-indices-v1"


def indices_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    return f"{ARCH}/ind_close_all_{d.day:02d}{d.month:02d}{d.year}.csv"


def parse_indices(payload: bytes, day_iso: str) -> tuple[list[dict], dict]:
    text = payload.decode("utf-8-sig", "replace")
    reader = csv.DictReader(text.splitlines())
    cols = reader.fieldnames or []
    rows = []
    for r in reader:
        name = (r.get("Index Name") or "").strip().upper()
        if not name:
            continue
        def num(*ks):
            for k in ks:
                try:
                    if r.get(k) not in (None, ""):
                        return float(str(r[k]).replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return None
        rows.append({"date": day_iso, "index_name": name,
                     "open": num("Open Index Value"), "high": num("High Index Value"),
                     "low": num("Low Index Value"), "close": num("Closing Index Value"),
                     "tri": num("TRI"), "pe": num("P/E"), "pb": num("P/B"),
                     "div_yield": num("Div Yield"),
                     "tri_source": "same-file" if "TRI" in cols else "absent"})
    return rows, {"columns": cols,
                  "schema_fingerprint": U.schema_fingerprint(cols)}


class NseIndices(B.Collector):
    source_name = "NSE"
    dataset_name = "indices"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              days: list[str] | None = None, http_get=None) -> B.FetchResult:
        started = U.utcnow()
        get = http_get or H.get
        day = datetime.now(timezone.utc).date().isoformat()
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        failures, hashes = [], []
        for d in days or [day]:
            url = indices_url(d)
            try:
                resp = get(url)
                art = B.store_raw(self.source_name, self.dataset_name, d,
                                  url.rsplit("/", 1)[-1], resp["bytes"], source_url=url,
                                  content_type=resp["headers"].get("content-type", ""),
                                  collector_version=COLLECTOR_VERSION)
                hashes.append(art["sha256"])
                rows, _rep = parse_indices(resp["bytes"], d)
                res.records_received += len(rows)
                if rows:
                    import pandas as pd
                    stat = PQ.upsert("indices", d[:7], pd.DataFrame(rows),
                                     ["date", "index_name"])
                    res.records_written += stat["added"]
            except H.HttpError as e:
                code = e.code or 0
                status = (B.FetchStatus.RATE_LIMITED if code == 429
                          else B.FetchStatus.SOURCE_BLOCKED if code in (401, 403)
                          else B.FetchStatus.SOURCE_UNAVAILABLE)
                failures.append({"day": d, "status": status.value, "note": str(e)[:200]})
                B.log_error(self.source_name, self.dataset_name, d, status.value,
                            str(e), code, 0, COLLECTOR_VERSION)
            except Exception as e:  # noqa: BLE001
                failures.append({"day": d, "status": "SOURCE_UNAVAILABLE",
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
                      expected_freshness="daily-post-close")
        return res
