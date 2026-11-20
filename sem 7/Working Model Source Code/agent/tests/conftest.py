"""Hermetic test DB: point sqlite_conn() at a per-session temp file.

Without this, tests share data/quantplus.db with production (evo population
cap, usage_daily ledger), so real rows — e.g. the 8 forward-paper founders —
break tests that assume an empty store, and tests pollute production data.
QP_DB_PATH is consumed by app.db.sqlite_conn; production default is unchanged.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_db_path = os.path.join(tempfile.mkdtemp(prefix="qp-test-"), "test.db")
os.environ["QP_DB_PATH"] = _db_path
# Never start paid background model calls from a test application's lifespan.
os.environ["STOCK_PREDICTION_WARM_ENABLED"] = "false"
# Keep tests on the deterministic offline key path even though the real .env now
# carries an Experiential Labs key (provider priority: experiential > openrouter).
os.environ["EXPLABS_API_KEY"] = ""
# The real .env also carries an Inception key, which now takes priority over
# Experiential Labs; neutralize it for the same reason.
os.environ["INCEPTION_API_KEY"] = ""

os.environ["WEBSITE_API_KEY"] = "offline-internal-test-key"


@pytest.fixture(autouse=True)
def isolated_gateway_quota_state():
    """Keep provider daily-quota state hermetic between tests.

    test_technical_pit_live makes a REAL provider call; when the shared free
    tier is spent (observed 2026-10-27) its 429 records a daily-quota reset on
    the process-wide gateway singleton AND in the persisted day ledger. Without
    this cleanup, every later test that consults gateway.quota_status() (e.g.
    warm_next) or constructs a Gateway() inherits that exhausted state.
    """
    import datetime as _dt

    from app.db import sqlite_conn

    def _clear_persisted():
        try:
            sqlite_conn().execute(
                "UPDATE usage_daily SET quota_reset=0 WHERE day=?",
                (_dt.date.today().isoformat(),))
            sqlite_conn().commit()
        except Exception:
            pass  # table/column not created yet in this session

    from app.gateway import codecraft
    _clear_persisted()
    codecraft.gateway._daily_quota_until.clear()
    yield
    _clear_persisted()
    codecraft.gateway._daily_quota_until.clear()
