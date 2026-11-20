"""BSE corporate-actions collector (§19, secondary feed)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.data_acquisition import actions_store as STORE
from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import util as U
from app.data_acquisition.nse.corporate_actions import NseCorporateActions

API = ("https://api.bseindia.com/BseIndiaAPI/api/CorpAction/w"
       "?scrip={scrip}&segment=Equity")
COLLECTOR_VERSION = "bse-ca-v1"


class BseCorporateActions(NseCorporateActions):
    source_name = "BSE"
    dataset_name = "corporate-actions"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              scrips: list[str] | None = None, day: str | None = None,
              http_get=None) -> B.FetchResult:
        started = U.utcnow()
        day = day or datetime.now(timezone.utc).date().isoformat()
        get = http_get or H.get
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        failures = []
        for scrip in scrips or []:
            url = API.format(scrip=scrip)
            try:
                resp = get(url)
                try:
                    payload = json.loads(resp["bytes"].decode("utf-8", "replace"))
                    rows = payload.get("Table", []) if isinstance(payload, dict) else []
                except ValueError:
                    res.invalid_records += 1
                    failures.append({"scrip": scrip, "status": "VALIDATION_FAILED",
                                     "note": "non-JSON response"})
                    continue
                art = B.store_raw(self.source_name, self.dataset_name, day,
                                  f"{scrip}.json", resp["bytes"], source_url=url,
                                  content_type="application/json",
                                  collector_version=COLLECTOR_VERSION)
                res.raw_hashes.append(art["sha256"])
                res.records_received += len(rows)
                for r in rows:
                    rec = STORE.normalize("BSE", bse_row(scrip, r))
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
                failures.append({"scrip": scrip, "status": status.value, "note": str(e)[:200]})
                B.log_error(self.source_name, self.dataset_name, day, status.value,
                            f"{scrip}: {e}", code, 0, COLLECTOR_VERSION)
            except Exception as e:  # noqa: BLE001
                failures.append({"scrip": scrip, "status": "SOURCE_UNAVAILABLE",
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


def bse_row(scrip: str, r: dict) -> dict:
    purpose = str(r.get("Purpose") or r.get("SUBJECT") or "")
    kind = ("DIVIDEND" if "dividend" in purpose.lower()
            else "SPLIT" if "split" in purpose.lower()
            else "BONUS" if "bonus" in purpose.lower()
            else "UNKNOWN")
    return {"id": r.get("Seq") or r.get("id"), "symbol": f"BSE-{scrip}",
            "action_type": kind, "ex_date": r.get("ExDate") or r.get("ex_date") or "",
            "record_date": r.get("RecordDate") or "", "ratio": r.get("Ratio") or "",
            "cash_amount": r.get("Dividend") or r.get("cash_amount"),
            "announcement_ts": r.get("AnnDate") or "", "source": "BSE",
            "isin": r.get("ISIN", "")}
