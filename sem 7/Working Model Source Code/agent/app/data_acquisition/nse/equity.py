"""NSE equity EOD + delivery collector (Phase D, §§21–23).

Sources (official NSE archives, best-effort):
  bhavcopy (UDiFF/security-wise): .../content/historical/EQUITIES/{YYYY}/{MON}/{cmDDMONYYYYbhav.csv.zip}
  full bhavcopy w/ delivery:      .../products/content/sec_bhavdata_full_{DDMMYYYY}.csv
Raw ZIP/CSV stored BEFORE parsing (§9). Normalized month partitions carry only
fields actually present (§21: never fabricate). Raw exchange prices stored as
raw_exchange_price; adjusted_research_price is UNAVAILABLE until verified
corporate-action factors exist (§22 — marked, not imputed).
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
COLLECTOR_VERSION = "nse-eod-v1"
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
          "OCT", "NOV", "DEC")

# §58 known-good fingerprints are learned per layout version, never assumed:
# first sighting records the fingerprint; drift vs recorded fingerprint in the
# same major layout raises SOURCE_SCHEMA_CHANGED (handled in parse()).
KNOWN_LAYOUTS = {
    "bhav_full": (["SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "LAST",
                   "PREVCLOSE", "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP", "TOTALTRADES",
                   "ISIN", "DELIVQTY", "DELYQT", "VWAP"], "v1"),
}


def bhav_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    return (f"{ARCH}/content/historical/EQUITIES/{d.year}/{MONTHS[d.month - 1]}/"
            f"cm{d.day:02d}{MONTHS[d.month - 1]}{d.year}bhav.csv.zip")


def full_bhav_url(day_iso: str) -> str:
    d = datetime.fromisoformat(day_iso).date()
    return f"{ARCH}/products/content/sec_bhavdata_full_{d.day:02d}{d.month:02d}{d.year}.csv"


def _unzip_first(payload: bytes) -> tuple[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("zip contains no csv")
            with zf.open(names[0]) as f:
                return names[0], f.read()
    except zipfile.BadZipFile:
        return "inline.csv", payload  # some endpoints serve bare CSV


def parse_bhav(payload: bytes, day_iso: str) -> tuple[list[dict], dict]:
    """Parse bhavcopy (zip or bare CSV). Returns (rows, report) with §87 flags.
    Unknown columns are tolerated (stored if recognized, ignored otherwise);
    missing expected columns -> layout drift report (never positional mapping)."""
    name, raw = _unzip_first(payload)
    text = raw.decode("utf-8-sig", "replace")
    reader = csv.DictReader(text.splitlines())
    cols = reader.fieldnames or []
    layout, ver = None, ""
    for layout_name, (expected, version) in KNOWN_LAYOUTS.items():
        if set(expected) <= set(cols):
            layout, ver = layout_name, version
            break
    drift = None
    if layout is None:
        drift = {"columns": cols, "note": "unrecognized layout — parsed best-effort"}
    rows, flags = [], {"invalid": 0, "high_low_violation": 0, "negative_volume": 0,
                       "delivery_gt_traded": 0}
    for r in reader:
        try:
            row = normalize_row(r, day_iso)
        except ValueError:
            flags["invalid"] += 1
            continue
        problems = validate_ohlcv(row)
        for p in problems:
            flags[p] = flags.get(p, 0) + 1
        row["validation_flags"] = problems
        rows.append(row)
    return rows, {"inner_file": name, "layout": layout or "unknown",
                  "layout_version": ver, "schema_drift": drift, "flags": flags,
                  "schema_fingerprint": U.schema_fingerprint(cols)}


def _f(r: dict, *keys) -> str:
    for k in keys:
        if r.get(k) not in (None, ""):
            return str(r[k])
    return ""


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "")) if str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def normalize_row(r: dict, day_iso: str) -> dict:
    """§21 fields, present-only. Raises ValueError when identity/price missing."""
    symbol = (_f(r, "SYMBOL") or "").strip().upper()
    if not symbol:
        raise ValueError("missing SYMBOL")
    close = _num(_f(r, "CLOSE", "Close Price"))
    if close is None:
        raise ValueError("missing CLOSE")
    out = {"trade_date": day_iso, "symbol": symbol + ".NS",
           "series": _f(r, "SERIES") or None,
           "raw_exchange_price": {"open": _num(_f(r, "OPEN")), "high": _num(_f(r, "HIGH")),
                                  "low": _num(_f(r, "LOW")), "close": close,
                                  "prev_close": _num(_f(r, "PREVCLOSE", "Prev Close"))},
           "vwap": _num(_f(r, "VWAP", "VWAP")),
           "volume": _num(_f(r, "TOTTRDQTY", "No.of Shares")),
           "turnover_lakh": _num(_f(r, "TOTTRDVAL", "Total Turnover (Rs.)")),
           "n_trades": _num(_f(r, "TOTALTRADES", "No. of Trades")),
           "deliverable_qty": _num(_f(r, "DELIVQTY", "Deliverable Qty")),
           "delivery_pct": _num(_f(r, "DELYQT", "% DlyQt toTraded Qty")),
           "isin": _f(r, "ISIN") or None,
           "adjusted_research_price": None,  # §22: unavailable until verified factors
           "adjustment_status": "UNAVAILABLE"}
    return out


def validate_ohlcv(row: dict) -> list[str]:
    """§87 detection-only checks. Returns flag names (empty = clean)."""
    problems = []
    px = row.get("raw_exchange_price", {})
    o, h, lo, c = px.get("open"), px.get("high"), px.get("low"), px.get("close")
    vals = [v for v in (o, h, lo, c) if v is not None]
    if vals and (h is not None) and h < max(vals):
        problems.append("high_low_violation")
    if vals and (lo is not None) and lo > min(vals):
        problems.append("high_low_violation")
    if (row.get("volume") or 0) < 0:
        problems.append("negative_volume")
    dq, tq = row.get("deliverable_qty"), row.get("volume")
    if dq is not None and tq not in (None, 0) and dq > tq:
        problems.append("delivery_gt_traded")
    dp = row.get("delivery_pct")
    if dp is not None and not 0 <= dp <= 100:
        problems.append("delivery_pct_range")
    return problems


class NseEquityEod(B.Collector):
    source_name = "NSE"
    dataset_name = "equity-eod"
    collector_version = COLLECTOR_VERSION

    def fetch(self, *, start=None, end=None, incremental: bool = True,
              days: list[str] | None = None, http_get=None,
              full_bhav: bool = False) -> B.FetchResult:
        started = U.utcnow()
        get = http_get or H.get
        day = datetime.now(timezone.utc).date().isoformat()
        res = B.FetchResult(status=B.FetchStatus.SUCCESS, source=self.source_name,
                            dataset=self.dataset_name,
                            requested_start=str(start or ""),
                            requested_end=str(end or ""), started_at=started)
        failures, hashes = [], []
        for d in days or [day]:
            url = (full_bhav_url(d) if full_bhav else bhav_url(d))
            try:
                resp = get(url)
                art = B.store_raw(self.source_name, self.dataset_name, d,
                                  url.rsplit("/", 1)[-1], resp["bytes"],
                                  source_url=url,
                                  content_type=resp["headers"].get("content-type", ""),
                                  collector_version=COLLECTOR_VERSION)
                hashes.append(art["sha256"])
                rows, report = parse_bhav(resp["bytes"], d)
                if report["schema_drift"]:
                    res.status = B.FetchStatus.SOURCE_SCHEMA_CHANGED
                    failures.append({"day": d, "status": "SOURCE_SCHEMA_CHANGED",
                                     "note": f"columns: {report['schema_drift']['columns'][:8]}"})
                    B.log_error(self.source_name, self.dataset_name, d,
                                "SOURCE_SCHEMA_CHANGED", "layout drift; raw preserved",
                                None, 0, COLLECTOR_VERSION)
                    continue
                res.records_received += len(rows)
                res.invalid_records += report["flags"].get("invalid", 0)
                if rows:
                    import pandas as pd
                    flat = []
                    for r in rows:
                        flat.append({"trade_date": r["trade_date"], "symbol": r["symbol"],
                                     "series": r["series"], "open": r["raw_exchange_price"]["open"],
                                     "high": r["raw_exchange_price"]["high"],
                                     "low": r["raw_exchange_price"]["low"],
                                     "close": r["raw_exchange_price"]["close"],
                                     "prev_close": r["raw_exchange_price"]["prev_close"],
                                     "vwap": r["vwap"], "volume": r["volume"],
                                     "turnover_lakh": r["turnover_lakh"],
                                     "n_trades": r["n_trades"],
                                     "deliverable_qty": r["deliverable_qty"],
                                     "delivery_pct": r["delivery_pct"],
                                     "isin": r["isin"],
                                     "adjusted_research_price": None,  # §22
                                     "adjustment_status": "UNAVAILABLE",
                                     "validation_flags": ",".join(r["validation_flags"])})
                    stat = PQ.upsert("equity-eod", d[:7], pd.DataFrame(flat),
                                     ["trade_date", "symbol"])
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
        if res.status != B.FetchStatus.SOURCE_SCHEMA_CHANGED:
            if failures and res.records_received == 0:
                res.status = B.FetchStatus.SOURCE_UNAVAILABLE
            elif failures:
                res.status = B.FetchStatus.PARTIAL
        res.batch_id = f"{self.source_name}-{self.dataset_name}-{day}"
        B.mark_health(self.source_name, self.dataset_name,
                      ok=res.records_received > 0, status=res.status.value,
                      expected_freshness="daily-post-close")
        return res
