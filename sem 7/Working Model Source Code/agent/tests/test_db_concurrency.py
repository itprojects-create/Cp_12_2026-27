"""SQLite concurrency: reproduce the shared-connection race, then prove the fix (§64).

Mirrors graph.py's analyst pattern: threads sharing DB access with concurrent
INSERT+commit. Pre-hardening this intermittently raises OperationalError
('no more rows available' / 'not an error'); post-hardening (thread-local
connections + WAL + busy timeout) it passes consistently.
"""
from __future__ import annotations

import threading

from app.db import sqlite_conn


def _stress(n_threads: int = 8, n_ops: int = 25) -> dict:
    sqlite_conn().execute("CREATE TABLE IF NOT EXISTS _stress (id INTEGER PRIMARY KEY, v TEXT)")
    sqlite_conn().execute("DELETE FROM _stress")
    sqlite_conn().commit()
    errors: list[str] = []

    def worker(k: int):
        try:
            for i in range(n_ops):
                sqlite_conn().execute("INSERT INTO _stress(v) VALUES (?)", (f"{k}-{i}",))
                sqlite_conn().commit()
        except Exception as e:  # noqa: BLE001 - collected, asserted below
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    n = sqlite_conn().execute("SELECT COUNT(*) FROM _stress").fetchone()[0]
    sqlite_conn().execute("DELETE FROM _stress")
    sqlite_conn().commit()
    return {"threads": n_threads, "ops_per_thread": n_ops, "rows": n,
            "errors": errors[:5], "n_errors": len(errors)}


def test_concurrent_commits_no_race():
    last = None
    for _ in range(3):  # repeat: the race is intermittent, persistence proves the fix
        last = _stress()
        assert last["n_errors"] == 0, last["errors"]
        assert last["rows"] == 8 * 25
