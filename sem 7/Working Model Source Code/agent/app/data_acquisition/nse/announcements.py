"""NSE corporate announcements collector (P0 feed, §15).

Source: NSE corporate-announcements API (official). Per-symbol recent fetch;
raw JSON responses stored as artifacts BEFORE parsing (§9). Parsed rows flow
into the existing immutable event store (no second store): identity bound
deterministically (symbol/ISIN/exchange/timestamps — never LLM-supplied),
then normalize → dedup/amendment → triage → rule classification → versioned
classification (§16 pipeline).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import util as U

API = ("https://www.nseindia.com/api/corporate-announcements"
       "?index=equities&symbol={symbol}")
COLLECTOR_VERSION = "nse-ann-v1"


class NseAnnouncements(B.Collector):
    source_name = "NSE"
    dataset_name = "announcements"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              symbols: list[str] | None = None, day: str | None = None,
              http_get=None) -> B.FetchResult:
        started = U.utcnow()
        day = day or datetime.now(timezone.utc).date().isoformat()
        symbols = symbols or []
        get = http_get or H.get
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        raw_hashes, failures = [], []
        for sym in symbols:
            url = API.format(symbol=sym.replace(".NS", ""))
            try:
                resp = get(url)
                payload = resp["bytes"]
                try:
                    rows = json.loads(payload.decode("utf-8", "replace"))
                    rows = rows if isinstance(rows, list) else rows.get("rows", [])
                except ValueError:
                    res.invalid_records += 1
                    failures.append({"symbol": sym, "status": "VALIDATION_FAILED",
                                     "note": "non-JSON response"})
                    B.log_error(self.source_name, self.dataset_name, day,
                                B.FetchStatus.VALIDATION_FAILED.value,
                                f"non-JSON response for {sym}", None, 0,
                                COLLECTOR_VERSION)
                    continue
                art = B.store_raw(self.source_name, self.dataset_name, day,
                                  f"{sym}.json", payload, source_url=url,
                                  content_type="application/json",
                                  collector_version=COLLECTOR_VERSION)
                raw_hashes.append(art["sha256"])
                res.records_received += len(rows)
                parsed = [parse_row(sym, r) for r in rows]
                parsed = [p for p in parsed if p]
                res.invalid_records += len(rows) - len(parsed)
                n_written, n_dup = integrate(parsed)
                res.records_written += n_written
                res.duplicates += n_dup
            except H.HttpError as e:
                code = e.code or 0
                if code in (401, 403):
                    status = B.FetchStatus.SOURCE_BLOCKED
                elif code == 429:
                    status = B.FetchStatus.RATE_LIMITED
                elif code and code >= 500:
                    status = B.FetchStatus.SOURCE_UNAVAILABLE
                else:
                    status = B.FetchStatus.SOURCE_UNAVAILABLE
                failures.append({"symbol": sym, "status": status.value, "note": str(e)[:200]})
                B.log_error(self.source_name, self.dataset_name, day, status.value,
                            f"{sym}: {e}", code, 0, COLLECTOR_VERSION)
            except Exception as e:  # noqa: BLE001 - one symbol never kills the run
                failures.append({"symbol": sym, "status": "SOURCE_UNAVAILABLE",
                                 "note": f"{type(e).__name__}: {e}"[:200]})
                B.log_error(self.source_name, self.dataset_name, day, "SOURCE_UNAVAILABLE",
                            f"{sym}: {e}", None, 0, COLLECTOR_VERSION)
        res.finished_at = U.utcnow()
        res.raw_hashes = raw_hashes
        res.source_failures = failures
        if failures and res.records_received == 0:
            res.status = B.FetchStatus.SOURCE_UNAVAILABLE
        elif failures:
            res.status = B.FetchStatus.PARTIAL
        res.batch_id = f"{self.source_name}-{self.dataset_name}-{day}"
        B.mark_health(self.source_name, self.dataset_name,
                      ok=res.records_received > 0, status=res.status.value,
                      expected_freshness="30min-trading-day")
        return res


def parse_row(symbol: str, row: dict) -> dict | None:
    """NSE API row -> event-store raw shape. Missing identity/timestamp -> None
    (never imputed, §1.5)."""
    title = str(row.get("headline") or row.get("title") or "").strip()
    ts = str(row.get("an_dt") or row.get("date") or row.get("broadcastDate") or "").strip()
    if not title or not ts:
        return None
    return {"exchange": "NSE", "source_id": str(row.get("seq") or row.get("id") or ""),
            "symbol": symbol, "company": str(row.get("companyName", ""))[:120],
            "publication_ts": ts, "title": title, "body": str(row.get("desc") or ""),
            "attachments": ([{"url": row["attach"]} for row in [row]
                             if row.get("attach")] if row.get("attach") else [])}


def integrate(parsed: list[dict]) -> tuple[int, int]:
    """Parsed rows -> immutable event store (§16). Returns (written, duplicates)."""
    from app.events import store as ST
    if not parsed:
        return 0, 0
    manifest = ST.ingest_batch("NSE", parsed, source_version=COLLECTOR_VERSION)
    return manifest["records_valid"], manifest["records_duplicate"]
