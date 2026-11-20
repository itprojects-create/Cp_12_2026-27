"""BSE corporate announcements collector (§17 secondary feed).

Source: BSE announcement JSON API (official, best-effort). Identity mapping:
ISIN equality links deterministically to NSE symbols where both carry it;
otherwise BSE rows stay symbol-only with ambiguous-link flags (§83 — never
force-linked). Same raw-first + immutable-store flow as NSE.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import util as U

API = ("https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
       "?strCat=-1&strPrevDate={prev}&strScrip={scrip}&strSearch=P"
       "&strToDate={to_date}&strType=C")
COLLECTOR_VERSION = "bse-ann-v1"


class BseAnnouncements(B.Collector):
    source_name = "BSE"
    dataset_name = "announcements"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              scrips: list[str] | None = None, day: str | None = None,
              http_get=None) -> B.FetchResult:
        started = U.utcnow()
        day = day or datetime.now(timezone.utc).date().isoformat()
        scrips = scrips or []
        get = http_get or H.get
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        raw_hashes, failures = [], []
        for scrip in scrips:
            url = API.format(prev=start or day, scrip=scrip, to_date=end or day)
            try:
                resp = get(url)
                try:
                    payload = json.loads(resp["bytes"].decode("utf-8", "replace"))
                    rows = payload.get("Table", []) if isinstance(payload, dict) else []
                except ValueError:
                    res.invalid_records += 1
                    failures.append({"scrip": scrip, "status": "VALIDATION_FAILED",
                                     "note": "non-JSON response"})
                    B.log_error(self.source_name, self.dataset_name, day,
                                B.FetchStatus.VALIDATION_FAILED.value,
                                f"non-JSON response for {scrip}", None, 0,
                                COLLECTOR_VERSION)
                    continue
                art = B.store_raw(self.source_name, self.dataset_name, day,
                                  f"{scrip}.json", resp["bytes"], source_url=url,
                                  content_type="application/json",
                                  collector_version=COLLECTOR_VERSION)
                raw_hashes.append(art["sha256"])
                res.records_received += len(rows)
                parsed = [p for p in (parse_row(r) for r in rows) if p]
                res.invalid_records += len(rows) - len(parsed)
                from app.data_acquisition.nse.announcements import integrate
                n_written, n_dup = integrate_bse(parsed)
                res.records_written += n_written
                res.duplicates += n_dup
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
                B.log_error(self.source_name, self.dataset_name, day, "SOURCE_UNAVAILABLE",
                            f"{scrip}: {e}", None, 0, COLLECTOR_VERSION)
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


def parse_row(row: dict) -> dict | None:
    """BSE API row -> event-store raw shape. ISIN retained for cross-linking."""
    title = str(row.get("HEADLINE") or row.get("SUBJECT") or "").strip()
    ts = str(row.get("NEWS_DT") or row.get("DissemDT") or "").strip()
    if not title or not ts:
        return None
    code = str(row.get("SCRIP_CD") or "")
    return {"exchange": "BSE", "source_id": code,
            "symbol": f"BSE-{code}" if code else "BSE-UNKNOWN",
            "company": str(row.get("SLONGNAME", ""))[:120],
            "publication_ts": ts, "title": title,
            "body": str(row.get("NEWSSUB") or ""),
            "isin": str(row.get("ISIN", "")),
            "attachments": ([{"url": row["ATTACHMENTNAME"]}]
                            if row.get("ATTACHMENTNAME") else [])}


def integrate_bse(parsed: list[dict]) -> tuple[int, int]:
    from app.events import store as ST
    if not parsed:
        return 0, 0
    # BSE symbols stay exchange-scoped (BSE-<code>, never rewritten to .NS:
    # scrip codes are not NSE symbols and mapping without a master would be
    # fabrication). Cross-exchange matching happens only via ISIN links.
    for p in parsed:
        p["symbol"] = str(p.get("symbol", "")).strip().upper() or "BSE-UNKNOWN"
    manifest = ST.ingest_batch("BSE", parsed, source_version=COLLECTOR_VERSION)
    return manifest["records_valid"], manifest["records_duplicate"]


def cross_link_bse_nse() -> dict:
    """Deterministic cross-exchange links (§17): the SAME corporate event links
    only on ISIN equality AND same publication date. Anything ambiguous
    (missing ISIN, multiple candidates) is counted, never force-linked (§83)."""
    from app.db import sqlite_conn
    from app.events import store as ST
    ST.init_tables()
    bse = sqlite_conn().execute(
        "SELECT record_id, isin, substr(publication_ts,1,10) FROM raw_events"
        " WHERE exchange='BSE'").fetchall()
    linked, ambiguous, no_match, no_isin = 0, 0, 0, 0
    for rid, isin, day in bse:
        if not (isin or "").strip():
            no_isin += 1  # unlinkable without ISIN — never force-linked (§83)
            continue
        cands = sqlite_conn().execute(
            "SELECT record_id FROM raw_events WHERE exchange='NSE' AND isin=?"
            " AND substr(publication_ts,1,10)=?", (isin, day)).fetchall()
        if len(cands) == 1:
            ST._link(rid, cands[0][0], "cross_source")
            ST._link(cands[0][0], rid, "cross_source")
            linked += 1
        elif len(cands) > 1:
            ambiguous += 1
        else:
            no_match += 1
    return {"linked": linked, "ambiguous_unlinked": ambiguous, "no_match": no_match,
            "no_isin_unlinkable": no_isin}
