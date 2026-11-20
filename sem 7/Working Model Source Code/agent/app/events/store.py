"""Immutable announcement store (P1, §§10–18).

Tables (shared SQLite ledger; hermetic in tests via QP_DB_PATH):
  event_batches(batch_id PK, source, started_at, ended_at, received, valid,
    duplicates, failed, source_version, ingestor_version, batch_hash, status)
  raw_events(record_id PK, exchange, source_id, symbol, company,
    exchange_ts, publication_ts, ingestion_ts, title, body, attach_meta,
    payload_hash, ingestor_version, source_status)
  normalized_events(record_id PK, normalized_title, normalized_body,
    raw_hash, normalized_hash, normalizer_version, ts)
  event_classifications(record_id, version, classifier_model, prompt_version,
    schema_version, taxonomy_version, classifier_version, classification,
    classification_hash, ts) — append-only (PK record_id+version)
  event_links(child_id, parent_id, relation, ts) — duplicate_of / amends
  source_failures(ts, source, kind, detail) — explicit outage log

Append-only: this module exposes NO update/delete for raw/normalized rows.
Corrections arrive as new normalizer/classifier versions (§1.4).
Identity (record_id) is deterministic: EV-{exchange}-{payload_hash12}.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.db import sqlite_conn
from app.events import textnorm as TN

INGESTOR_VERSION = "INGEST_V1"
FAILURE_KINDS = ("SOURCE_UNAVAILABLE", "SOURCE_SCHEMA_CHANGED",
                 "PARTIAL_FETCH", "RATE_LIMITED")


def init_tables() -> None:
    c = sqlite_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS event_batches
        (batch_id TEXT PRIMARY KEY, source TEXT, started_at TEXT, ended_at TEXT,
         received INTEGER, valid INTEGER, duplicates INTEGER, failed INTEGER,
         source_version TEXT, ingestor_version TEXT, batch_hash TEXT, status TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS raw_events
        (record_id TEXT PRIMARY KEY, exchange TEXT, source_id TEXT, symbol TEXT,
         company TEXT, exchange_ts TEXT, publication_ts TEXT, ingestion_ts TEXT,
         title TEXT, body TEXT, attach_meta TEXT, payload_hash TEXT,
         ingestor_version TEXT, source_status TEXT)""")
    # Additive P1 migration: ISIN for deterministic cross-exchange linking.
    cols = [r[1] for r in c.execute("PRAGMA table_info(raw_events)").fetchall()]
    if "isin" not in cols:
        c.execute("ALTER TABLE raw_events ADD COLUMN isin TEXT DEFAULT ''")
    c.execute("""CREATE TABLE IF NOT EXISTS normalized_events
        (record_id TEXT PRIMARY KEY, normalized_title TEXT, normalized_body TEXT,
         raw_hash TEXT, normalized_hash TEXT, normalizer_version TEXT, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS event_classifications
        (record_id TEXT, version INTEGER, classifier_model TEXT, prompt_version TEXT,
         schema_version TEXT, taxonomy_version TEXT, classifier_version TEXT,
         classification TEXT, classification_hash TEXT, ts TEXT,
         PRIMARY KEY (record_id, version))""")
    c.execute("""CREATE TABLE IF NOT EXISTS event_links
        (child_id TEXT, parent_id TEXT, relation TEXT, ts TEXT,
         PRIMARY KEY (child_id, parent_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS source_failures
        (ts TEXT, source TEXT, kind TEXT, detail TEXT)""")
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def payload_hash(exchange: str, symbol: str, title: str, body: str,
                 publication_ts: str) -> str:
    return hashlib.sha256(json.dumps(
        {"exchange": exchange, "symbol": symbol, "title": title, "body": body,
         "publication_ts": publication_ts}, sort_keys=True).encode()).hexdigest()[:16]


def record_id_for(exchange: str, payload_hash: str) -> str:
    return f"EV-{exchange}-{payload_hash[:12]}"


def log_source_failure(source: str, kind: str, detail: str = "") -> None:
    """Explicit outage record (§18). Never an empty success."""
    if kind not in FAILURE_KINDS:
        raise ValueError(f"unknown failure kind {kind!r}")
    init_tables()
    sqlite_conn().execute(
        "INSERT INTO source_failures(ts, source, kind, detail) VALUES (?,?,?,?)",
        (_now(), source, kind, detail[:500]))
    sqlite_conn().commit()


def _near_dup(a: str, b: str, threshold: float = 0.9) -> bool:
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / max(len(ta), len(tb)) >= threshold


def ingest_batch(source: str, raws: list[dict],
                 source_version: str = "nse-web-v1") -> dict:
    """Append a batch of raw announcements. Returns the §17 manifest dict and
    persists it. Duplicate/amended detection links rows instead of discarding
    (amendments preserved, §14). Idempotent: re-ingesting the same payload
    yields the same record_id and a duplicate link, never a second row."""
    from app.events.normalize import normalize_symbol
    init_tables()
    started = _now()
    received = len(raws)
    valid = duplicates = failed = 0
    kept_hashes: list[str] = []
    for r in raws:
        try:
            exchange = str(r.get("exchange") or source).upper()
            # NSE symbols use panel form (.NS); BSE rows keep exchange scope
            # (BSE-<code>) — scrip codes are never rewritten as NSE symbols.
            if exchange == "BSE":
                symbol = str(r.get("symbol", "")).strip().upper() or "BSE-UNKNOWN"
            else:
                symbol = normalize_symbol(r.get("symbol", ""))
            title = str(r.get("title", "")).strip()
            body = str(r.get("body", ""))
            pub = str(r.get("publication_ts") or r.get("timestamp") or "")
            if exchange not in ("NSE", "BSE") or len(symbol) < 5 or not title or not pub:
                failed += 1
                continue
            ph = payload_hash(exchange, symbol, title, body, pub)
            rid = record_id_for(exchange, ph)
            existing = sqlite_conn().execute(
                "SELECT record_id FROM raw_events WHERE record_id=?", (rid,)).fetchone()
            norm_title = TN.normalize_text(title)
            norm_body = TN.normalize_text(body)
            if existing:
                duplicates += 1
                _link(rid, rid, "duplicate_of")
            else:
                # same exchange source-id re-ingested with changes -> amendment chain
                sid = str(r.get("source_id") or "")
                prior = None
                if sid:
                    prior = sqlite_conn().execute(
                        "SELECT record_id, title, body FROM raw_events"
                        " WHERE exchange=? AND source_id=? ORDER BY ingestion_ts DESC LIMIT 1",
                        (exchange, sid)).fetchone()
                sqlite_conn().execute(
                    "INSERT INTO raw_events(record_id, exchange, source_id, symbol, company,"
                    " exchange_ts, publication_ts, ingestion_ts, title, body, attach_meta,"
                    " payload_hash, ingestor_version, source_status, isin)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, exchange, sid or None, symbol, str(r.get("company", ""))[:120],
                     str(r.get("exchange_ts") or pub), pub, _now(), title, body,
                     json.dumps(r.get("attachments", []))[:500], ph,
                     INGESTOR_VERSION, "OK", str(r.get("isin", ""))[:12]))
                sqlite_conn().execute(
                    "INSERT OR IGNORE INTO normalized_events(record_id, normalized_title,"
                    " normalized_body, raw_hash, normalized_hash, normalizer_version, ts)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (rid, norm_title, norm_body, ph,
                     TN.text_hash(norm_title + "\n" + norm_body),
                     TN.NORMALIZER_VERSION, _now()))
                if prior and prior[0] != rid:
                    old_norm = TN.normalize_text((prior[1] or "") + "\n" + (prior[2] or ""))
                    new_norm = TN.normalize_text(title + "\n" + body)
                    rel = ("amends" if _looks_amended(title, prior[1])
                           or not _near_dup(old_norm, new_norm) else "duplicate_of")
                    _link(rid, prior[0], rel)
                valid += 1
            kept_hashes.append(ph)
        except Exception:  # noqa: BLE001 - one bad row never kills the batch
            failed += 1
    batch_hash = hashlib.sha256("".join(sorted(kept_hashes)).encode()).hexdigest()[:16]
    ended = _now()
    batch_id = f"BATCH-{source}-{ended[:10]}-{batch_hash[:8]}"
    manifest = {"batch_id": batch_id, "source": source, "started_at": started,
                "ended_at": ended, "records_received": received, "records_valid": valid,
                "records_duplicate": duplicates, "records_failed": failed,
                "source_version": source_version, "ingestor_version": INGESTOR_VERSION,
                "batch_hash": batch_hash,
                "status": "OK" if failed == 0 else ("PARTIAL_FETCH" if valid else "FAILED")}
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO event_batches(batch_id, source, started_at, ended_at,"
        " received, valid, duplicates, failed, source_version, ingestor_version,"
        " batch_hash, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, source, started, ended, received, valid, duplicates, failed,
         source_version, INGESTOR_VERSION, batch_hash, manifest["status"]))
    sqlite_conn().commit()
    return manifest


def _looks_amended(new_title: str, old_title: str | None) -> bool:
    t = (new_title or "").lower()
    return any(k in t for k in ("corrigendum", "amendment", "revised", "clarification"))


def _link(child: str, parent: str, relation: str) -> None:
    sqlite_conn().execute(
        "INSERT OR IGNORE INTO event_links(child_id, parent_id, relation, ts)"
        " VALUES (?,?,?,?)", (child, parent, relation, _now()))
    sqlite_conn().commit()


def get_raw(record_id: str) -> dict | None:
    init_tables()
    r = sqlite_conn().execute(
        "SELECT record_id, exchange, source_id, symbol, company, exchange_ts,"
        " publication_ts, ingestion_ts, title, body, attach_meta, payload_hash,"
        " ingestor_version, source_status, isin FROM raw_events WHERE record_id=?",
        (record_id,)).fetchone()
    if not r:
        return None
    cols = ["record_id", "exchange", "source_id", "symbol", "company", "exchange_ts",
            "publication_ts", "ingestion_ts", "title", "body", "attach_meta",
            "payload_hash", "ingestor_version", "source_status", "isin"]
    return dict(zip(cols, r))


def links_for(record_id: str) -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT child_id, parent_id, relation, ts FROM event_links"
        " WHERE child_id=? OR parent_id=?", (record_id, record_id)).fetchall()
    return [{"child": r[0], "parent": r[1], "relation": r[2], "ts": r[3]} for r in rows]


def append_classification(record_id: str, classification: dict,
                          classifier_model: str = "rules-v1",
                          prompt_version: str = "m12",
                          schema_version: str = "announcement-v1",
                          taxonomy_version: str = "EVENT_TAXONOMY_V1",
                          classifier_version: str = "classifier-v1") -> dict:
    """Append-only versioned classification (§§25-26). Reclassification adds a
    new version row; no update path exists. Returns the version record."""
    import hashlib as _h
    import json as _j
    from app.events.schemas import validate_extraction
    init_tables()
    if get_raw(record_id) is None:
        raise ValueError(f"unknown event {record_id} — classify stored raws only")
    gated = validate_extraction(classification)  # directive/smuggle gate
    body = gated.model_dump(mode="json")
    chash = _h.sha256(_j.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    row = sqlite_conn().execute(
        "SELECT COALESCE(MAX(version),0) FROM event_classifications WHERE record_id=?",
        (record_id,)).fetchone()
    version = int(row[0]) + 1
    sqlite_conn().execute(
        "INSERT INTO event_classifications(record_id, version, classifier_model,"
        " prompt_version, schema_version, taxonomy_version, classifier_version,"
        " classification, classification_hash, ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (record_id, version, classifier_model, prompt_version, schema_version,
         taxonomy_version, classifier_version, _j.dumps(body, sort_keys=True),
         chash, _now()))
    sqlite_conn().commit()
    return {"record_id": record_id, "version": version,
            "taxonomy_version": taxonomy_version,
            "classifier_version": classifier_version,
            "classification_hash": chash}


def classifications_for(record_id: str) -> list[dict]:
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT version, classifier_model, prompt_version, schema_version,"
        " taxonomy_version, classifier_version, classification,"
        " classification_hash, ts FROM event_classifications"
        " WHERE record_id=? ORDER BY version", (record_id,)).fetchall()
    return [{"version": r[0], "classifier_model": r[1], "prompt_version": r[2],
             "schema_version": r[3], "taxonomy_version": r[4],
             "classifier_version": r[5], "classification": json.loads(r[6]),
             "classification_hash": r[7], "ts": r[8]} for r in rows]


def store_stats() -> dict:
    init_tables()
    c = sqlite_conn()
    return {
        "batches": c.execute("SELECT COUNT(*) FROM event_batches").fetchone()[0],
        "raw": c.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0],
        "normalized": c.execute("SELECT COUNT(*) FROM normalized_events").fetchone()[0],
        "classifications": c.execute("SELECT COUNT(*) FROM event_classifications").fetchone()[0],
        "links": c.execute("SELECT COUNT(*) FROM event_links").fetchone()[0],
        "failures": c.execute("SELECT COUNT(*) FROM source_failures").fetchone()[0],
    }


def announcements_in_range(start_iso: str, end_iso: str,
                           taxonomy_version: str | None = None) -> list[dict]:
    """Raw + latest-classification rows with publication_ts in [start, end].

    Returns dicts carrying identity (deterministic, from raw) + classification
    (latest version only; optionally pinned to a taxonomy version) +
    normalized text. Empty range -> [] (infancy, never imputed)."""
    init_tables()
    rows = sqlite_conn().execute(
        "SELECT record_id, exchange, symbol, publication_ts, ingestion_ts, title, body"
        " FROM raw_events WHERE publication_ts >= ? AND publication_ts <= ?"
        " ORDER BY publication_ts", (start_iso, end_iso)).fetchall()
    out = []
    for r in rows:
        cls = sqlite_conn().execute(
            "SELECT classification, taxonomy_version, classifier_version, version"
            " FROM event_classifications WHERE record_id=? ORDER BY version DESC LIMIT 1",
            (r[0],)).fetchone()
        if taxonomy_version is not None and (cls is None or cls[1] != taxonomy_version):
            continue
        norm = sqlite_conn().execute(
            "SELECT normalized_title, normalized_body, normalized_hash"
            " FROM normalized_events WHERE record_id=?", (r[0],)).fetchone()
        out.append({"record_id": r[0], "exchange": r[1], "symbol": r[2],
                    "publication_ts": r[3], "ingestion_ts": r[4],
                    "title": r[5], "body": r[6],
                    "classification": json.loads(cls[0]) if cls else None,
                    "taxonomy_version": cls[1] if cls else None,
                    "classifier_version": cls[2] if cls else None,
                    "classification_version": cls[3] if cls else None,
                    "normalized_hash": norm[2] if norm else None})
    return out
