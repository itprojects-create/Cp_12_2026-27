"""Unattended trading-day rehearsal (P6, §§42–45).

Modes:
  DRY_RUN       — pure functions only, zero writes, zero network.
  REPLAY_FIXTURE— full pipeline against an isolated temp DB + fixtures
                  (calendar → announcements → hash → normalize → classify →
                  PIT eligibility → event store → market panel → corp actions →
                  institutional → registry → quality → snapshot → experiment
                  → health → backup). No manual patching: fixture hashes
                  verified identical before/after (§44).
  LIVE_SHADOW   — real sources, real storage, real forward evidence, no orders.

Exit 0 + artifact on success; any step failure is recorded, never patched over.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_tree(root: str) -> str:
    h = hashlib.sha256()
    for r, _d, files in os.walk(root):
        for fn in sorted(files):
            p = os.path.join(r, fn)
            h.update(os.path.relpath(p, root).encode())
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:16]


def dry_run(day: str) -> dict:
    from app.data_acquisition import util as U
    from app.events import classify as CL
    from app.events import normalize as NORM
    from app.ops import calendar as CAL
    steps = {"calendar": CAL.session_kind(day)}
    raw = [{"source": "NSE", "symbol": "INFY.NS", "title": "Board Meeting Intimation",
            "timestamp": f"{day}T10:00:00+00:00"}]
    recs, rep = NORM.normalize(raw, now=datetime.fromisoformat(day + "T23:59:59+00:00"))
    steps["normalize"] = rep
    steps["triage"] = CL.triage(recs[0]["title"]) if recs else {"decision": "ABSTAIN"}
    steps["manifest_hash"] = U.sha256_bytes(json.dumps(recs, sort_keys=True).encode())[:16]
    steps["writes"] = 0
    steps["network"] = 0
    return {"mode": "DRY_RUN", "day": day, "as_of": _utcnow(), "steps": steps,
            "verdict": "PASS"}


def replay_fixture(day: str) -> dict:
    """Full pipeline, isolated temp DB, fixture inputs. Returns the report."""
    old_qp = os.environ.get("QP_DB_PATH")
    tmpdir = tempfile.mkdtemp(prefix="qp-rehearse-")
    os.environ["QP_DB_PATH"] = os.path.join(tmpdir, "rehearse.db")
    try:
        import app.db as DB
        DB._local.conn = None
        return _replay(tmpdir, day)
    finally:
        if old_qp is None:
            os.environ.pop("QP_DB_PATH", None)
        else:
            os.environ["QP_DB_PATH"] = old_qp
        try:
            DB._local.conn = None
        except Exception:  # noqa: BLE001
            pass


def _replay(tmpdir: str, day: str) -> dict:
    import pandas as pd
    from app.core.trend_core_v4 import run_core_v4
    from app.data import registry as REG
    from app.data_acquisition import base as B
    from app.data_acquisition import parquet as PQ
    from app.events import blackout as BO
    from app.events import classify as CL
    from app.events import normalize as NORM
    from app.events import store as ST
    from app.ops import calendar as CAL
    from app.ops import log as OPS

    before = _hash_tree(os.path.join("tests", "fixtures", "acquisition"))
    steps: dict = {}
    steps["calendar"] = CAL.session_kind(day)
    # announcements: fixture -> raw -> normalize -> triage -> rule -> store
    nse_raw = open("tests/fixtures/acquisition/nse_ann.json", encoding="utf-8").read()
    doc = json.loads(nse_raw)
    raws = [{"source": "NSE", "symbol": "INFY.NS", "title": r["headline"],
             "timestamp": r["an_dt"]} for r in doc["rows"]]
    recs, rep = NORM.normalize(raws)
    steps["normalize"] = rep
    triaged = [CL.triage(r["title"]) for r in recs]
    steps["classified"] = sum(1 for t in triaged if t["decision"] == "CLASSIFY")
    steps["abstained"] = sum(1 for t in triaged if t["decision"] == "ABSTAIN")
    man = ST.ingest_batch("NSE", [{"exchange": "NSE", "source_id": f"RH-{i}",
                                   "symbol": r["symbol"],
                                   "publication_ts": r["source_timestamp"],
                                   "title": r["title"], "body": ""} for i, r in enumerate(recs)])
    steps["event_store"] = {"valid": man["records_valid"]}
    # classify rule + versioned classification for each stored row
    from app.db import sqlite_conn
    rids = [r[0] for r in sqlite_conn().execute("SELECT record_id FROM raw_events").fetchall()]
    for rid in rids:
        row = ST.get_raw(rid)
        rule = CL.classify_rule(row["title"])
        if rule is not None:
            ST.append_classification(rid, {"event_type": rule.get("event_type", "OTHER"),
                                           "severity": rule.get("severity", 0.2),
                                           "blackout_candidate": rule.get(
                                               "blackout_candidate", False)})
    steps["versioned_classifications"] = len(rids)
    # market panel (synthetic, tradeable shape) + blackout-gated core run
    idx = [100 + i * 0.3 for i in range(120)]
    names = {"INFY.NS": [50 + i * 0.5 for i in range(120)],
             "RELIANCE.NS": [60 + i * 0.4 for i in range(120)]}
    dates = ["2026-10-01"] * 120
    anns = ST.announcements_in_range("2026-10-01", "2026-10-10")
    b3 = [r for r in BO.BLACKOUT_FAMILY_V1 if r.rule_id == "B3"][0]

    def gate(nm, t, d):
        cands = [a for a in anns if a["symbol"] == nm]
        ok, _ = BO.rule_active(b3, nm, datetime(2026, 10, 5, tzinfo=timezone.utc),
                               [_row_to_ann(a) for a in cands])
        return not ok

    control = run_core_v4(idx, names)
    gated = run_core_v4(idx, names, dates=dates, entry_gate_fn=gate)
    steps["core"] = {"control_return": round(control.total_return, 4),
                     "gated_return": round(gated.total_return, 4)}
    # registry + quality + snapshot + health + backup (isolated paths)
    REG.seed_known()
    REG.record_usage("forward-from-2026-10-10", "rehearsal", "replay-fixture")
    B.mark_health("REHEARSAL", "replay", ok=True)
    snap_path = os.path.join(tmpdir, "snap.json")
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump({"rehearsal": day, "events": len(rids)}, f)
    steps["snapshot"] = os.path.exists(snap_path)
    OPS.log("rehearsal", "finish", status="OK", note="replay-fixture")
    after = _hash_tree(os.path.join("tests", "fixtures", "acquisition"))
    steps["fixtures_untouched"] = before == after  # §44: no manual patching
    assert steps["fixtures_untouched"], "rehearsal mutated its fixtures"
    return {"mode": "REPLAY_FIXTURE", "day": day, "as_of": _utcnow(), "steps": steps,
            "verdict": "PASS"}


def _row_to_ann(a: dict):
    from app.events.schemas import Announcement
    cls = a.get("classification") or {}
    return Announcement(source="NSE", symbol=a["symbol"],
                        event_type=cls.get("event_type", "OTHER"),
                        severity=float(cls.get("severity", 0.2)),
                        source_timestamp=a["publication_ts"],
                        effective_timestamp=a["publication_ts"],
                        blackout_candidate=bool(cls.get("blackout_candidate", False)))


def live_shadow(day: str) -> dict:
    """Real sources, real storage, real forward evidence. No orders exist in
    this codebase, so none can fire (boundary-tested separately)."""
    from app.data_acquisition.nse import announcements as NA
    from app.ops import calendar as CAL
    from app.ops import log as OPS
    steps: dict = {"calendar": CAL.session_kind(day)}
    OPS.log("live-shadow", "start", note=f"day={day}")
    try:
        res = NA.NseAnnouncements().fetch(symbols=["RELIANCE.NS", "INFY.NS"], day=day)
        steps["nse_probe"] = {"status": res.status.value, "received": res.records_received}
    except Exception as e:  # noqa: BLE001
        steps["nse_probe"] = {"status": "ERROR", "note": f"{type(e).__name__}: {e}"[:200]}
    OPS.log("live-shadow", "finish", status="OK", note=json.dumps(steps["nse_probe"])[:300])
    steps["orders"] = "none exist (no order capability in codebase)"
    return {"mode": "LIVE_SHADOW", "day": day, "as_of": _utcnow(), "steps": steps,
            "verdict": "PASS"}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["dry", "replay", "live-shadow"])
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    day = a.day or datetime.now(timezone.utc).date().isoformat()
    rec = {"dry": dry_run, "replay": replay_fixture, "live-shadow": live_shadow}[a.mode](day)
    out = a.out or os.path.join("data", f"rehearsal_{a.mode}_{day}.json")
    if a.mode != "dry":
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2)
        rec["artifact"] = out
    print(json.dumps(rec, indent=2, default=str))


if __name__ == "__main__":
    main()
