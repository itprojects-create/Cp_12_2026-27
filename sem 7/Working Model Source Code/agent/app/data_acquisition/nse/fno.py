"""NSE derivatives collectors (§§28–31): F&O bhavcopy, participant OI/volume,
FII derivatives statistics. Official archives, best-effort URLs (deal/derivative
archive paths have changed historically — drift returns SOURCE_SCHEMA_CHANGED,
never fabricated rows). Raw tables preserve EXACT source field names (§31);
derived features live in features/pcr.py, never in raw ingestion.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import parquet as PQ
from app.data_acquisition import util as U

ARCH = "https://nsearchives.nseindia.com"
COLLECTOR_VERSION = "nse-fno-v1"
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
          "OCT", "NOV", "DEC")


def fo_bhav_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    mon = MONTHS[d.month - 1]
    return (f"{ARCH}/content/historical/DERIVATIVES/{d.year}/{mon}/"
            f"fo{d.day:02d}{mon}{d.year}bhav.csv.zip")


def participant_oi_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    return (f"{ARCH}/content/fo/participant_wise_open_interest_"
            f"{d.day:02d}{d.month:02d}{d.year}.csv")


def participant_vol_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    return (f"{ARCH}/content/fo/participant_wise_trading_volume_"
            f"{d.day:02d}{d.month:02d}{d.year}.csv")


def fii_stats_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    return (f"{ARCH}/content/fo/fii_stats_{d.day:02d}-{MONTHS[d.month - 1].title()}-"
            f"{d.year}.xls")


def _unzip_first(payload: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("zip contains no csv")
            with zf.open(names[0]) as f:
                return f.read()
    except zipfile.BadZipFile:
        return payload


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "")) if str(v).strip() not in ("", "-") else None
    except (TypeError, ValueError):
        return None


def parse_fo_bhav(payload: bytes, day_iso: str) -> tuple[list[dict], dict]:
    """§28 contract fields, present-only. OI<0 flagged (§87), never repaired."""
    text = _unzip_first(payload).decode("utf-8-sig", "replace")
    reader = csv.DictReader(text.splitlines())
    cols = reader.fieldnames or []
    rows, invalid, neg_oi = [], 0, 0
    for r in reader:
        symbol = (r.get("SYMBOL") or "").strip().upper()
        if not symbol:
            invalid += 1
            continue
        oi = _num(r.get("OPEN_INT"))
        if oi is not None and oi < 0:
            neg_oi += 1
        rows.append({
            "trade_date": day_iso, "symbol": symbol,
            "expiry": (r.get("EXPIRY_DT") or "")[:10] or None,
            "instrument_type": (r.get("INSTRUMENT") or "").strip().upper() or None,
            "strike": _num(r.get("STRIKE_PR")), "option_type": (r.get("OPTION_TYP") or "").strip().upper() or None,
            "open": _num(r.get("OPEN")), "high": _num(r.get("HIGH")),
            "low": _num(r.get("LOW")), "close": _num(r.get("CLOSE")),
            "settle_price": _num(r.get("SETTLE_PR")),
            "contracts": _num(r.get("CONTRACTS")), "volume": _num(r.get("VAL_INLAKH")),
            "open_interest": oi, "change_in_oi": _num(r.get("CHG_IN_OI")),
            "source_columns": ",".join(cols[:4])})
    return rows, {"columns": cols, "invalid": invalid, "negative_oi": neg_oi,
                  "schema_fingerprint": U.schema_fingerprint(cols)}


def parse_participant(payload: bytes, day_iso: str, kind: str) -> tuple[list[dict], dict]:
    """Participant OI or volume file. OI and volume stay SEPARATE datasets (§30)."""
    text = payload.decode("utf-8-sig", "replace")
    reader = csv.DictReader(text.splitlines())
    cols = reader.fieldnames or []
    rows, invalid = [], 0
    for r in reader:
        client = (r.get("Client Type") or r.get("CLIENT") or "").strip().upper()
        if not client:
            invalid += 1
            continue
        row = {"trade_date": day_iso, "client_type": client}
        for k, v in r.items():
            if k and k not in ("Client Type", "CLIENT"):
                row[f"src_{k.strip().lower().replace(' ', '_')}"] = _num(v)
        rows.append(row)
    return rows, {"columns": cols, "invalid": invalid,
                  "schema_fingerprint": U.schema_fingerprint(cols)}


class NseFno(B.Collector):
    source_name = "NSE"
    dataset_name = "fno-bhavcopy"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              days: list[str] | None = None, http_get=None) -> B.FetchResult:
        return _fetch_files(self, "fno-bhavcopy", days, parse_fo_bhav,
                            fo_bhav_url, http_get, start, end,
                            ("trade_date", "symbol", "expiry", "instrument_type",
                             "strike", "option_type"))


class NseParticipantOi(B.Collector):
    source_name = "NSE"
    dataset_name = "participant-oi"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              days: list[str] | None = None, http_get=None) -> B.FetchResult:
        import functools
        return _fetch_files(self, "participant-oi", days,
                            lambda p, d: parse_participant(p, d, "OI"),
                            participant_oi_url, http_get, start, end,
                            ("trade_date", "client_type"))


class NseParticipantVol(B.Collector):
    source_name = "NSE"
    dataset_name = "participant-volume"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              days: list[str] | None = None, http_get=None) -> B.FetchResult:
        return _fetch_files(self, "participant-volume", days,
                            lambda p, d: parse_participant(p, d, "VOL"),
                            participant_vol_url, http_get, start, end,
                            ("trade_date", "client_type"))


def _fetch_files(collector: B.Collector, dataset: str, days, parse_fn,
                 url_fn, http_get, start, end, keys) -> B.FetchResult:
    from datetime import timezone as _tz
    started = U.utcnow()
    get = http_get or H.get
    day = datetime.now(_tz.utc).date().isoformat()
    res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=collector.source_name,
                        dataset=dataset, requested_start=str(start or ""),
                        requested_end=str(end or ""), started_at=started)
    failures, hashes = [], []
    for d in days or [day]:
        url = url_fn(d)
        try:
            resp = get(url)
            art = B.store_raw(collector.source_name, dataset, d,
                              url.rsplit("/", 1)[-1], resp["bytes"], source_url=url,
                              content_type=resp["headers"].get("content-type", ""),
                              collector_version=collector.collector_version)
            hashes.append(art["sha256"])
            rows, rep = parse_fn(resp["bytes"], d)
            res.records_received += len(rows)
            res.invalid_records += rep.get("invalid", 0)
            if rows:
                import pandas as pd
                stat = PQ.upsert(dataset, d[:7], pd.DataFrame(rows), list(keys))
                res.records_written += stat["added"]
            else:
                res.status = B.FetchStatus.NO_DATA
        except H.HttpError as e:
            code = e.code or 0
            status = (B.FetchStatus.RATE_LIMITED if code == 429
                      else B.FetchStatus.SOURCE_BLOCKED if code in (401, 403)
                      else B.FetchStatus.SOURCE_UNAVAILABLE)
            failures.append({"day": d, "status": status.value, "note": str(e)[:200]})
            B.log_error(collector.source_name, dataset, d, status.value,
                        str(e), code, 0, collector.collector_version)
        except Exception as e:  # noqa: BLE001
            failures.append({"day": d, "status": "SOURCE_UNAVAILABLE",
                             "note": f"{type(e).__name__}: {e}"[:200]})
    res.finished_at = U.utcnow()
    res.raw_hashes = hashes
    res.source_failures = failures
    if res.status != B.FetchStatus.NO_DATA:
        if failures and res.records_received == 0:
            res.status = B.FetchStatus.SOURCE_UNAVAILABLE
        elif failures:
            res.status = B.FetchStatus.PARTIAL
    res.batch_id = f"{collector.source_name}-{dataset}-{day}"
    B.mark_health(collector.source_name, dataset,
                  ok=res.records_received > 0, status=res.status.value,
                  expected_freshness="daily-post-settlement")
    return res
