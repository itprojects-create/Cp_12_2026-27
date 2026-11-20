"""CDSL final FPI/FII flows (§27): manual-import-first collector.

CDSL publishes final (settled/revised) flows on its own cadence and page
layouts; scraping assumptions are NOT baked in. Supported paths, in order:
manual import of a legitimately acquired CDSL export (primary), then
best-effort fetch of documented publication URLs. FINAL rows live in their own
dataset (`fpi-final`) — provisional NSE observations are never overwritten.

Cross-validation (§46): compare_provisional_final() grades NSE-provisional vs
CDSL-final pairs as MATCH / MINOR_DIFFERENCE / CONFLICT with a disclosed
tolerance. Disagreements are stored, never silently resolved.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import parquet as PQ
from app.data_acquisition import util as U

COLLECTOR_VERSION = "cdsl-fpi-v1"
TOLERANCE_CR = 500.0  # minor-difference bound, disclosed


def parse_cdsl_csv(payload: bytes, day_iso: str) -> tuple[list[dict], dict]:
    text = payload.decode("utf-8-sig", "replace")
    reader = csv.DictReader(text.splitlines())
    cols = reader.fieldnames or []
    rows = []
    for r in reader:
        date = (r.get("Date") or r.get("date") or day_iso)[:10]
        try:
            net = float(str(r.get("Net Investment") or r.get("net") or "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        rows.append({"date": date, "category": "FPI", "net_cr": net, "status": "FINAL"})
    return rows, {"columns": cols, "schema_fingerprint": U.schema_fingerprint(cols)}


class CdslFpi(B.Collector):
    source_name = "CDSL"
    dataset_name = "fpi-final"
    collector_version = COLLECTOR_VERSION

    def import_file(self, path: str, day: str | None = None) -> B.FetchResult:
        """Manual import of a legitimately acquired CDSL export (§72 pattern)."""
        started = U.utcnow()
        day = day or datetime.now(timezone.utc).date().isoformat()
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name, started_at=started)
        with open(path, "rb") as f:
            payload = f.read()
        art = B.store_raw(self.source_name, self.dataset_name, day,
                          path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
                          payload, source_url=f"manual-import:{path}",
                          ingestion_mode="MANUAL_IMPORT",
                          collector_version=COLLECTOR_VERSION)
        res.raw_hashes = [art["sha256"]]
        rows, _rep = parse_cdsl_csv(payload, day)
        res.records_received = len(rows)
        if rows:
            import pandas as pd
            stat = PQ.upsert("fpi-final", day[:7], pd.DataFrame(rows), ["date", "category"])
            res.records_written = stat["added"]
        else:
            res.status = B.FetchStatus.NO_DATA
        res.finished_at = U.utcnow()
        res.batch_id = f"{self.source_name}-{self.dataset_name}-{day}"
        B.mark_health(self.source_name, self.dataset_name,
                      ok=res.records_received > 0, status=res.status.value,
                      expected_freshness="fortnightly-manual")
        return res

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              **kw) -> B.FetchResult:
        started = U.utcnow()
        res = B.FetchResult(status=B.FetchStatus.SOURCE_UNAVAILABLE,
                            source=self.source_name, dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started,
                            finished_at=started)
        res.source_failures = [{"status": "SUBSCRIPTION_REQUIRED",
                                "note": "CDSL finals via manual import (see import_file); "
                                        "no automated endpoint assumed"}]
        B.log_error(self.source_name, self.dataset_name, "", "SUBSCRIPTION_REQUIRED",
                    "manual import required", None, 0, COLLECTOR_VERSION)
        return res


def compare_provisional_final(prov_net: float, final_net: float,
                              tolerance_cr: float = TOLERANCE_CR) -> dict:
    """§46 cross-validation grade. Stored by callers, never auto-resolved."""
    diff = abs(prov_net - final_net)
    if diff == 0:
        grade = "MATCH"
    elif diff <= tolerance_cr:
        grade = "MINOR_DIFFERENCE"
    else:
        grade = "CONFLICT"
    return {"provisional": prov_net, "final": final_net, "abs_diff": diff,
            "tolerance_cr": tolerance_cr, "grade": grade}
