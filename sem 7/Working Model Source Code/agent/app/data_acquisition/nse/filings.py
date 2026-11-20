"""Financial-results + shareholding collectors (§§34–38).

Manual-import-first (legitimately acquired XBRL/PDF exports); automated NSE
XBRL endpoints are session-gated and attempted best-effort only. Normalized
filing rows always carry broadcast-based availability (§36); revisions append.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import filings as FIL
from app.data_acquisition import http as H
from app.data_acquisition import util as U

COLLECTOR_VERSION = "nse-filings-v1"
# Documented endpoint shapes (session-gated; attempted best-effort, never hacked).
XBRL_SEARCH = "https://www.nseindia.com/api/corporate-filings?symbol={symbol}&type={kind}"


class NseFilings(B.Collector):
    source_name = "NSE"
    dataset_name = "filings"
    collector_version = COLLECTOR_VERSION

    def import_file(self, symbol: str, filing_type: str, period_start: str,
                    period_end: str, broadcast_ts: str, path: str,
                    standalone_consolidated: str | None = None) -> dict:
        """Manual import of a legitimately acquired filing export (§72 pattern)."""
        with open(path, "rb") as f:
            payload = f.read()
        is_xml = path.lower().endswith((".xml", ".xbrl"))
        return FIL.ingest_filing(
            symbol, filing_type, period_start, period_end, broadcast_ts,
            xbrl_bytes=payload if is_xml else None,
            pdf_bytes=None if is_xml else payload, day=None,
            standalone_consolidated=standalone_consolidated,
            collector_version=COLLECTOR_VERSION)

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              symbols: list[str] | None = None, kind: str = "financial-results",
              http_get=None) -> B.FetchResult:
        started = U.utcnow()
        get = http_get or H.get
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        failures = []
        for sym in symbols or []:
            url = XBRL_SEARCH.format(symbol=sym.replace(".NS", ""), kind=kind)
            try:
                resp = get(url)
                art = B.store_raw(self.source_name, self.dataset_name,
                                  datetime.now(timezone.utc).date().isoformat(),
                                  f"{sym}_filings.json", resp["bytes"], source_url=url,
                                  collector_version=COLLECTOR_VERSION)
                res.raw_hashes.append(art["sha256"])
                res.records_received += 1
                # Listing responses reference filing artifacts; artifact download
                # + XBRL ingest happens per reference via import_file once URLs
                # are verified reachable (no blind bulk download).
                res.records_written += 0
            except H.HttpError as e:
                code = e.code or 0
                status = (B.FetchStatus.RATE_LIMITED if code == 429
                          else B.FetchStatus.SOURCE_BLOCKED if code in (401, 403)
                          else B.FetchStatus.SOURCE_UNAVAILABLE)
                failures.append({"symbol": sym, "status": status.value, "note": str(e)[:200]})
                B.log_error(self.source_name, self.dataset_name, "", status.value,
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
        res.batch_id = f"{self.source_name}-{self.dataset_name}-filings"
        B.mark_health(self.source_name, self.dataset_name,
                      ok=res.records_received > 0, status=res.status.value,
                      expected_freshness="event-driven-manual")
        return res
