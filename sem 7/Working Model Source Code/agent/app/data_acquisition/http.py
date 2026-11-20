"""Shared robust HTTP layer (§8). One place for all exchange HTTP.

Bounded: connection/read timeouts, small retry cap, Retry-After honoring,
exponential backoff with cap, per-host pacing, ETag/Last-Modified conditional
GETs, gzip, content-type validation. No CAPTCHA solving, no session
circumvention, no unlimited retries.
"""
from __future__ import annotations

import gzip
import time
import urllib.request

DEFAULT_TIMEOUT_S = 30.0
RETRY_MAX = 3
BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 30.0
MIN_INTERVAL_S = 1.5  # per-host pacing
USER_AGENT = "QuantPlus-Research/1.0 (contact: research; polite-delay)"

_last_hit: dict[str, float] = {}


def _host(url: str) -> str:
    return url.split("/")[2] if "://" in url else url.split("/")[0]


def pace(url: str, min_interval_s: float = MIN_INTERVAL_S) -> None:
    """Polite per-host pacing. Sleeps only the outstanding deficit."""
    h, now = _host(url), time.monotonic()
    wait = min_interval_s - (now - _last_hit.get(h, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[h] = time.monotonic()


def _backoff(attempt: int) -> float:
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** attempt))


class HttpError(Exception):
    def __init__(self, message: str, code: int | None = None,
                 retry_after_s: float | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after_s = retry_after_s


def get(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S,
        retries: int = RETRY_MAX, min_interval_s: float = MIN_INTERVAL_S,
        expect_content: str | None = None, etag: str | None = None,
        last_modified: str | None = None) -> dict:
    """GET with bounds. Returns {status, bytes, headers, etag, last_modified,
    not_modified}. Raises HttpError (429/5xx retried to cap, then raised)."""
    if retries < 0 or retries > 10:
        raise ValueError("retries must be in [0,10]")
    last: Exception | None = None
    for attempt in range(retries + 1):
        pace(url, min_interval_s)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept-Encoding": "gzip"})
        if etag:
            req.add_header("If-None-Match", etag)
        if last_modified:
            req.add_header("If-Modified-Since", last_modified)
        try:
            import socket
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(timeout_s)
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    code = getattr(resp, "status", 200)
                    if code == 304:
                        return {"status": 304, "bytes": b"", "headers": {},
                                "etag": etag, "last_modified": last_modified,
                                "not_modified": True}
                    raw = resp.read()
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    if code == 429 or (isinstance(code, int) and 500 <= code < 600):
                        retry_after = None
                        try:
                            retry_after = float(headers.get("retry-after", ""))
                        except (TypeError, ValueError):
                            retry_after = None
                        raise HttpError(f"HTTP {code} for {url}", code=code,
                                        retry_after_s=retry_after)
                    if isinstance(code, int) and code != 200:
                        raise HttpError(f"HTTP {code} for {url} (no retry)", code=code)
                    if headers.get("content-encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    if expect_content and expect_content not in headers.get(
                            "content-type", ""):
                        raise HttpError(
                            f"unexpected content-type {headers.get('content-type')!r}"
                            f" for {url}", code=code)
                    return {"status": code, "bytes": raw, "headers": headers,
                            "etag": headers.get("etag"), "not_modified": False,
                            "last_modified": headers.get("last-modified")}
            finally:
                socket.setdefaulttimeout(old_timeout)
        except HttpError as e:
            last = e
            if e.code == 429 or (e.code and 500 <= e.code < 600):
                if attempt < retries:
                    time.sleep(e.retry_after_s or _backoff(attempt))
                    continue
            raise
        except Exception as e:  # noqa: BLE001 - network is hostile; bounded below
            code, retry_after = getattr(e, "code", None), None
            if code is not None:
                try:
                    retry_after = float(dict(getattr(e, "headers", {}) or {}).get(
                        "Retry-After", ""))
                except (TypeError, ValueError):
                    retry_after = None
                last = HttpError(f"HTTP {code} for {url}", code=code,
                                 retry_after_s=retry_after)
                if (code == 429 or 500 <= code < 600) and attempt < retries:
                    time.sleep(retry_after or _backoff(attempt))
                    continue
                raise last from e
            last = e
            if attempt < retries:
                time.sleep(_backoff(attempt))
                continue
            raise HttpError(f"fetch failed for {url}: {type(e).__name__}: {e}") from e
    raise HttpError(f"fetch failed for {url} after {retries} retries: {last}")
