"""DB layer: Postgres (structured) + Mongo (raw I/O). Falls back to SQLite/in-memory if URLs absent."""
from __future__ import annotations
import sqlite3
import threading

# §64 hardening: ONE connection PER THREAD (never shared across threads),
# WAL mode + busy timeout so concurrent collectors/sessions serialize safely.
# Same path, same schema, same call shape — behavior preserved, race removed.
_local = threading.local()


def _connect(db_path: str) -> sqlite3.Connection:
    import os
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions
        (id TEXT PRIMARY KEY, instrument TEXT, as_of TEXT, config_hash TEXT, status TEXT, decision TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS theses
        (instrument TEXT, version INTEGER, status TEXT, body TEXT, created_at TEXT,
         PRIMARY KEY (instrument, version))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS session_events
        (session_id TEXT, ts TEXT, stage TEXT, agent TEXT, status TEXT, ref TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS checkpoints
        (session_id TEXT, stage TEXT, payload TEXT, updated_at TEXT,
         PRIMARY KEY (session_id, stage))""")
    conn.execute("CREATE INDEX IF NOT EXISTS sessions_lookup ON sessions(instrument, config_hash, as_of DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS session_events_lookup ON session_events(session_id, ts)")
    conn.execute("""CREATE TABLE IF NOT EXISTS usage_daily
        (day TEXT PRIMARY KEY, tokens INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_settlements
        (session_id TEXT PRIMARY KEY, ticker TEXT, trade_date TEXT,
         raw_ret REAL, alpha_ret REAL, holding_days INTEGER,
         resolved_at TEXT, reflection TEXT)""")
    conn.commit()
    return conn


def sqlite_conn() -> sqlite3.Connection:
    import os
    # Env override for hermetic tests: QP_DB_PATH points pytest at a temp DB so
    # test rows never touch the production ledger (evo population cap,
    # usage_daily token counts). Default is unchanged for production.
    db_path = os.environ.get("QP_DB_PATH", "data/quantplus.db")
    if getattr(_local, "path", None) != db_path or getattr(_local, "conn", None) is None:
        try:
            old = getattr(_local, "conn", None)
            if old is not None:
                old.close()
        except Exception:  # noqa: BLE001 - best-effort close
            pass
        _local.conn = _connect(db_path)
        _local.path = db_path
    return _local.conn

def pg_ok(url: str) -> bool:
    return bool(url and url.startswith(("postgresql://", "postgres://")))

def mongo_ok(url: str) -> bool:
    return bool(url and url.startswith("mongodb://"))
