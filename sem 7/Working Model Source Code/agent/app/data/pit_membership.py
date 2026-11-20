"""Time-varying point-in-time index membership (P0 — highest-priority correctness).

The previous layer (`pit_universe.start_date_universe`) froze membership at the
window START: mid-window exits stayed, joiners were cut once. This module makes
membership a per-rebalance lookup: `membership_at(universe, decision_timestamp)`.

Source: the same vendored CSV (NEVER edited) read through `pit_universe`
accessors. Interval-based: a constituent is visible only when membership was
effective AND knowable by the decision timestamp (hard PIT rule, §5).

Knowability proxy (disclosed): the CSV carries no per-row announcement
timestamp, so `effective_from` is the knowability bound. Index membership
changes are announced before they take effect in practice; any residual
announcement lag is a documented PARTIAL-grade limitation, never silent.
Rows from strict sources (press_release/merger/amendment) grade VERIFIED;
other sources grade PARTIAL and are excluded in strict mode.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.data import pit_universe as PU

UNIVERSE_INDEX_IDS = {"nifty50": "217", "nifty500": "221"}
OPEN = "9999-12-31"


class MembershipInterval(BaseModel):
    model_config = {"frozen": True}
    instrument_id: str  # .NS panel form (e.g. RELIANCE.NS)
    universe_id: str  # nifty50 | nifty500
    effective_from: str  # YYYY-MM-DD inclusive
    effective_to: str | None = None  # None = still member (open)
    announcement_timestamp: str | None = None  # None = effective_from is the proxy
    source_timestamp: str | None = None
    ingestion_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str
    source_record_id: str | None = None
    pit_confidence: Literal["VERIFIED", "PARTIAL", "UNKNOWN"] = "PARTIAL"
    source_hash: str = ""
    # §39 source class: subscription feeds and press-release reconstructions
    # are never treated as equivalent; carried on every interval + snapshot.
    source_class: Literal["OFFICIAL_SUBSCRIPTION",
                          "PRESS_RELEASE_RECONSTRUCTION"] = "PRESS_RELEASE_RECONSTRUCTION"


def _to_ns(sym: str) -> str:
    s = (sym or "").strip().upper()
    return s if s.endswith(".NS") else s + ".NS"


def _load_intervals(path: str | None = None, strict: bool = True) -> tuple[list[MembershipInterval], dict]:
    """Build + validate intervals. Overlapping same-symbol intervals and
    malformed rows are rejected with counts (never silently merged)."""
    rows = PU.history_rows(path)
    renames_path = PU.DEFAULT_RENAMES_PATH
    import json as _j
    import os as _os
    renames: list[dict] = []
    if _os.path.exists(renames_path):
        try:
            doc = _j.load(open(renames_path, encoding="utf-8-sig"))
            inner = doc.get("renames", []) if isinstance(doc, dict) else []
            renames = [e for e in inner if isinstance(e, dict) and e.get("old") and e.get("new")]
        except (ValueError, OSError):
            renames = []
    intervals: list[MembershipInterval] = []
    rejected = {"malformed": 0, "non_strict_excluded": 0}
    for i, r in enumerate(rows):
        sym = (r.get("symbol") or "").strip()
        frm = (r.get("valid_from") or "")[:10]
        to = (r.get("valid_to") or "")[:10] or None
        src = (r.get("source") or "").strip()
        if not sym or len(frm) != 10:
            rejected["malformed"] += 1
            continue
        if to is not None and (len(to) != 10 or to < frm):
            rejected["malformed"] += 1
            continue
        if src not in PU.STRICT_SOURCES:
            rejected["non_strict_excluded"] += 1
            if strict:
                continue
        # date-aware rename (same convention as pit_universe)
        canon = sym
        for e in renames:
            if sym == e["old"] and e.get("effective_date") and e["effective_date"] <= frm:
                canon = e["new"]
        idx_ids = {v: k for k, v in UNIVERSE_INDEX_IDS.items()}
        universe = idx_ids.get(r.get("index_id", ""), r.get("index_id", ""))
        verified = src in PU.STRICT_SOURCES
        intervals.append(MembershipInterval(
            instrument_id=_to_ns(canon), universe_id=universe,
            effective_from=frm, effective_to=to,
            source=src, source_record_id=f"row-{i}",
            pit_confidence="VERIFIED" if verified else "PARTIAL",
            source_hash=hashlib.sha256(
                json.dumps(r, sort_keys=True).encode()).hexdigest()[:16]))
    # overlap guard: same-SOURCE overlapping spells are data errors (reject).
    # Cross-source overlaps (e.g. press_release vs snapshot_floor re-inclusion
    # rows, as in the real vendored file) are AMBIGUITY, not error: both spells
    # are retained, counted, and force PARTIAL status wherever visible.
    # Membership sets are unaffected (overlap agrees on membership); confidence
    # is what degrades. Nothing is silently merged.
    ambiguous: list[dict] = []
    by_key: dict[tuple[str, str], list[MembershipInterval]] = {}
    for iv in intervals:
        by_key.setdefault((iv.universe_id, iv.instrument_id), []).append(iv)
    for key, spells in by_key.items():
        ordered = sorted(spells, key=lambda s: s.effective_from)
        for a, b in zip(ordered, ordered[1:]):
            a_end = a.effective_to or OPEN
            if b.effective_from <= a_end:
                if a.source == b.source:
                    raise ValueError(f"overlapping membership intervals for {key}: "
                                     f"{a.effective_from}..{a_end} vs {b.effective_from}.."
                                     f"{b.effective_to or OPEN} (same source: reject)")
                ambiguous.append({"universe": key[0], "instrument": key[1],
                                  "a": f"{a.effective_from}..{a_end} ({a.source})",
                                  "b": f"{b.effective_from}..{b.effective_to or OPEN} "
                                       f"({b.source})"})
    return intervals, {"n_intervals": len(intervals), "rejected": rejected,
                       "ambiguous_overlaps": ambiguous,
                       "source_version": PU.source_version(path)}


def is_visible(iv: MembershipInterval, decision_date: str,
               use_announcement: bool = True) -> bool:
    """Hard PIT rule (§5): effective AND knowable by the decision date."""
    d = decision_date[:10]
    if not iv.effective_from <= d:
        return False
    if iv.effective_to is not None and d > iv.effective_to:
        return False
    if use_announcement and iv.announcement_timestamp is not None:
        return iv.announcement_timestamp[:10] <= d
    return True


_LOAD_CACHE: dict[tuple, tuple[list[MembershipInterval], dict]] = {}


def _loaded(path: str | None, strict: bool) -> tuple[list[MembershipInterval], dict]:
    """Single load per (path, strict) per process. Source is vendored and NEVER
    edited; clear_cache() resets for tests that swap fixture files."""
    key = (path or "__default__", strict)
    if key not in _LOAD_CACHE:
        _LOAD_CACHE[key] = _load_intervals(path, strict)
    return _LOAD_CACHE[key]


def membership_at(universe_id: str, decision_timestamp,
                  strict: bool = True, path: str | None = None) -> dict:
    """Deterministic snapshot contract (§4). Same timestamp -> same bytes.

    pit_status: VERIFIED (all visible rows strict-sourced), PARTIAL (weak rows
    present or excluded), UNKNOWN (no history coverage for this universe/date —
    caller must abstain from changes, never liquidate on UNKNOWN).
    """
    if isinstance(decision_timestamp, datetime):
        d10 = decision_timestamp.date().isoformat()
        dts = decision_timestamp.isoformat()
    else:
        dts = str(decision_timestamp)
        d10 = dts[:10]
    version = PU.source_version(path)
    intervals, load_meta = _loaded(path, strict)
    vis = [iv for iv in intervals
           if iv.universe_id == universe_id and is_visible(iv, d10)]
    members = sorted({iv.instrument_id for iv in vis})
    n_verified = sum(1 for iv in vis if iv.pit_confidence == "VERIFIED")
    mh = hashlib.sha256(json.dumps(members).encode()).hexdigest()[:16]
    universe_known = any(iv.universe_id == universe_id for iv in intervals)
    amb_keys = {(a["universe"], a["instrument"])
                for a in load_meta.get("ambiguous_overlaps", [])}
    ambiguous_visible = any((iv.universe_id, iv.instrument_id) in amb_keys for iv in vis)
    if not universe_known:
        status = "UNKNOWN"
    elif not members and d10 < min(
            (iv.effective_from for iv in intervals if iv.universe_id == universe_id),
            default=OPEN):
        status = "UNKNOWN"  # predates history — unverifiable, abstain
    elif (load_meta["rejected"]["non_strict_excluded"] > 0 or len(vis) > n_verified
            or ambiguous_visible):
        status = "PARTIAL"
    else:
        status = "VERIFIED"
    coverage = (n_verified / len(vis) if vis else 0.0)
    return {"members": members, "decision_timestamp": dts,
            "membership_source_version": version, "membership_hash": mh,
            "coverage": round(coverage, 4),
            "missing_records": load_meta["rejected"]["non_strict_excluded"]
            if strict else 0,
            "ambiguous_visible": ambiguous_visible,
            "source_class": "PRESS_RELEASE_RECONSTRUCTION",
            "pit_status": status, "strict": strict}


def clear_cache() -> None:
    _LOAD_CACHE.clear()
