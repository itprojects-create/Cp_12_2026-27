"""Corpse registry: failed research becomes an asset (§§8, 29, 30)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import sqlite_conn
from app.research_memory import store as ST


def bury(fp_value: str, idea: dict, failure_reason: str, metrics: dict,
         evidence_required: str = "") -> dict:
    """Write (or refresh) a corpse. Idempotent per fingerprint."""
    ST.init_tables()
    if not evidence_required:
        evidence_required = default_evidence_required(idea, failure_reason)
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO research_corpses(fp, body, failure_reason,"
        " evidence_required, ts) VALUES (?,?,?,?,?)",
        (fp_value, json.dumps(idea, sort_keys=True), failure_reason,
         evidence_required, datetime.now(timezone.utc).isoformat()))
    sqlite_conn().commit()
    return {"fp": fp_value, "failure_reason": failure_reason,
            "evidence_required": evidence_required}


def default_evidence_required(idea: dict, failure_reason: str) -> str:
    """§30 — what would change the verdict. Concrete, not dogma."""
    return ("Reconsider only on: (a) new PIT data covering an unseen regime, or "
            "(b) a new independent data source, or (c) a mechanism change with a "
            "materially different fingerprint. "
            f"Failed as: {failure_reason}. Idea was: {str(idea.get('title', idea))[:160]}")


def allowed_reuse(fp_value: str) -> str:
    """Permitted reuse carved out of a corpse (e.g. delivery: context, not alpha)."""
    corpse = ST.get_corpse_by_fp(fp_value)
    if corpse is None:
        return ""
    return str(corpse["body"].get("allowed_reuse", ""))
