"""Benchmark real completed research on an isolated DB; never call models.

TestClient measures in-process HTTP serving, not WAN or browser rendering.
The source database is opened read-only and only one completed run is copied.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="qp-serving-benchmark-") as directory:
        os.environ["QP_DB_PATH"] = str(Path(directory) / "benchmark.db")
        os.environ["STOCK_PREDICTION_WARM_ENABLED"] = "false"
        from app.api import stocks
        from app.config import settings
        from app.db import sqlite_conn
        from app.main import app
        from fastapi.testclient import TestClient
        source = sqlite3.connect(f"file:{(ROOT / 'data/quantplus.db').as_posix()}?mode=ro", uri=True)
        row = source.execute("SELECT * FROM sessions WHERE instrument='HDFCBANK.NS' AND config_hash=? "
                             "AND status='done' AND decision IS NOT NULL ORDER BY as_of DESC LIMIT 1",
                             (stocks.prediction_config(),)).fetchone()
        if not row:
            raise SystemExit("No completed HDFCBANK research for the current configuration; warm it first.")
        conn = sqlite_conn()
        conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", row)
        for checkpoint in source.execute("SELECT * FROM checkpoints WHERE session_id=?", (row[0],)):
            conn.execute("INSERT INTO checkpoints VALUES (?,?,?,?)", checkpoint)
        for event in source.execute("SELECT * FROM session_events WHERE session_id=?", (row[0],)):
            conn.execute("INSERT INTO session_events VALUES (?,?,?,?,?,?)", event)
        conn.commit()
        source.close()
        # One read-only benchmark connection; close it before Windows temp cleanup.
        stocks.sqlite_conn = lambda: conn
        stocks.G.sqlite_conn = lambda: conn
        settings.WEBSITE_API_KEY = "benchmark-only-key"
        settings.STOCK_PREDICTION_WARM_ENABLED = False
        def forbidden(*args, **kwargs):
            raise AssertionError("Snapshot serving must not execute a model")
        stocks.G.run_session = forbidden
        with TestClient(app) as client:
            times = []
            for _ in range(100):
                start = time.perf_counter()
                response = client.get("/api/v1/stocks/HDFCBANK/prediction", headers={"X-Quantplus-Key": "benchmark-only-key"})
                times.append((time.perf_counter() - start) * 1000)
                response.raise_for_status()
                result = response.json()
                assert result["as_of"] == row[2]
                assert result["decision"] == json.loads(row[5])
            report = {"instrument": "HDFCBANK", "requests": len(times),
                      "p50_ms": round(statistics.median(times), 3),
                      "p95_ms": round(sorted(times)[94], 3), "max_ms": round(max(times), 3),
                      "as_of": row[2], "analyst_reports": len(result["reports"]),
                      "model_calls": 0, "measurement": "in-process HTTP; real saved research; isolated DB"}
            print(json.dumps(report, indent=2))
        conn.close()


if __name__ == "__main__":
    main()
