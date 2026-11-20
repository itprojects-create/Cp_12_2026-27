"""Attachment fetch with host allowlist (§§18, 69, 89).

Only NSE/BSE official hosts are fetchable — arbitrary URLs are refused (no
SSRF, no exfiltration path). Every attachment is hashed; same URL serving new
bytes records a new version + flag. No OCR: PDF text extraction attempted only
when pypdf is importable, otherwise stored raw with a note.
"""
from __future__ import annotations

from app.data_acquisition import base as B
from app.data_acquisition import http as H
from app.data_acquisition import util as U

ALLOWED_HOSTS = ("nsearchives.nseindia.com", "www.nseindia.com",
                 "www.bseindia.com", "api.bseindia.com")


def allowed(url: str) -> bool:
    host = url.split("/")[2].lower() if "://" in url else ""
    return host in ALLOWED_HOSTS


def fetch_attachment(url: str, day: str, *, timeout_s: float = 30.0) -> dict:
    """Fetch + hash an attachment. Returns record (no exception on refusal —
    refusals are data, logged by the caller into source_failures)."""
    if not allowed(url):
        return {"url": url, "status": "REFUSED_HOST",
                "note": "host not in attachment allowlist (§69)"}
    try:
        resp = H.get(url, timeout_s=timeout_s, expect_content=None)
    except H.HttpError as e:
        return {"url": url, "status": "SOURCE_UNAVAILABLE", "note": str(e)[:200]}
    data = resp["bytes"]
    digest = U.sha256_bytes(data)
    art = B.store_raw("attachments", "event-attachments", day,
                      url.rsplit("/", 1)[-1][:80] or "attachment",
                      data, source_url=url,
                      content_type=resp["headers"].get("content-type", ""),
                      collector_version="attach-v1")
    text_note = "stored raw only"
    if art["path"].lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(art["path"])
            n_pages = len(reader.pages)
            text_note = f"pdf stored; {n_pages} pages (text extraction on demand)"
        except ImportError:
            text_note = "pdf stored raw; pypdf absent, no OCR attempted (§18)"
    return {"url": url, "status": "STORED", "sha256": digest,
            "mime": resp["headers"].get("content-type", ""),
            "size": len(data), "artifact": art["path"], "note": text_note}
