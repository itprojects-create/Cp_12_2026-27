"""NSE corporate-actions collector (§19).

Source: NSE corporate-actions API (official, best-effort). Raw responses stored
before parsing; rows normalized to the §19 schema and upserted idempotently.
Filing linkage + PIT confidence via actions_store (never imputed here).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.data_acquisition import actions_store as STORE
from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import util as U

API = ("https://www.nseindia.com/api/corporates-corporateActions"
       "?index=equities&symbol={symbol}")
COLLECTOR_VERSION = "nse-ca-v1"


class NseCorporateActions(B.Collector):
    source_name = "NSE"
    dataset_name = "corporate-actions"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              symbols: list[str] | None = None, day: str | None = None,
              http_get=None) -> B.FetchResult:
        started = U.utcnow()
        day = day or datetime.now(timezone.utc).date().isoformat()
        get = http_get or H.get
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        failures = []
        for sym in symbols or []:
            url = API.format(symbol=sym.replace(".NS", ""))
            try:
                resp = get(url)
                try:
                    payload = json.loads(resp["bytes"].decode("utf-8", "replace"))
                    rows = payload if isinstance(payload, list) else payload.get("rows", [])
                except ValueError:
                    res.invalid_records += 1
                    failures.append({"symbol": sym, "status": "VALIDATION_FAILED",
                                     "note": "non-JSON response"})
                    continue
                art = B.store_raw(self.source_name, self.dataset_name, day,
                                  f"{sym}.json", resp["bytes"], source_url=url,
                                  content_type="application/json",
                                  collector_version=COLLECTOR_VERSION)
                res.raw_hashes.append(art["sha256"])
                res.records_received += len(rows)
                for r in rows:
                    rec = STORE.normalize("NSE", nse_row(sym, r))
                    if rec is None:
                        res.invalid_records += 1
                        continue
                    STORE.upsert(rec)
                    res.records_written += 1
            except H.HttpError as e:
                code = e.code or 0
                status = (B.FetchStatus.RATE_LIMITED if code == 429
                          else B.FetchStatus.SOURCE_BLOCKED if code in (401, 403)
                          else B.FetchStatus.SOURCE_UNAVAILABLE)
                failures.append({"symbol": sym, "status": status.value, "note": str(e)[:200]})
                B.log_error(self.source_name, self.dataset_name, day, status.value,
                            f"{sym}: {e}", code, 0, COLLECTOR_VERSION)
            except Exception as e:  # noqa: BLE001
                failures.append({"symbol": sym, "status": "SOURCE_UNAVAILABLE",
                                 "note": f"{type(e).__name__}: {e}"[:200]})
        res.finished_at = U.utcnow()
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


def nse_row(symbol: str, r: dict) -> dict:
    purpose = str(r.get("purpose") or r.get("subject") or "")
    kind = ("DIVIDEND" if "dividend" in purpose.lower()
            else "SPLIT" if "split" in purpose.lower()
            else "BONUS" if "bonus" in purpose.lower()
            else "BUYBACK" if "buyback" in purpose.lower()
            else "UNKNOWN")
    return {"id": r.get("seq") or r.get("id"), "symbol": symbol,
            "action_type": kind, "ex_date": r.get("exDate") or r.get("ex_date") or "",
            "record_date": r.get("recordDate") or "", "ratio": r.get("ratio") or "",
            "cash_amount": r.get("dividend") or r.get("cash_amount"),
            "announcement_ts": r.get("announcementDate") or "",
            "source": "NSE", "isin": r.get("isin", "")}
