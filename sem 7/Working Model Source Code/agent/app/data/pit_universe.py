"""Point-in-time index membership from history (prereg_pit_universe.md).

Source: nse_index_membership_history.csv (vendored upstream, NEVER edited).
Strict sources = {'press_release','merger','amendment'} — see prereg §1 for the
documented deviation from the upstream doc's 'circular' wording.
Attribution (CC BY 4.0, required in every report using this):
  Membership: Jha, A. (2026). NSE Historical Membership (Point-in-Time).
  github.com/aditya-jha/nse-historical-membership. Derived from public NSE
  Indices press releases and NSE circulars. CC BY 4.0.
"""
from __future__ import annotations

import csv
import json
import os

ATTRIBUTION = (
    "Membership: Jha, A. (2026). NSE Historical Membership (Point-in-Time). "
    "github.com/aditya-jha/nse-historical-membership. Derived from public NSE "
    "Indices press releases and NSE circulars. CC BY 4.0."
)

DEFAULT_MEMBERSHIP_PATH = (
    os.environ.get("PIT_MEMBERSHIP_PATH")
    or r"D:\Model\data\reference\nse_index_membership_history.csv"
)
DEFAULT_RENAMES_PATH = (
    os.environ.get("PIT_RENAMES_PATH")
    or r"D:\Model\data\reference\nse_symbol_renames.json"
)

STRICT_SOURCES = {"press_release", "merger", "amendment"}

# Far-future sentinel for open-ended spells (empty valid_to = still member).
_OPEN = "9999-12-31"


def _read_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"PIT membership file missing: {path} — no silent fallback universe.")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def history_rows(path: str | None = None) -> list[dict]:
    """Public read accessor for the vendored membership history (P0 time-varying
    layer builds intervals from these rows; no behavior change here)."""
    return _read_rows(path or DEFAULT_MEMBERSHIP_PATH)


def source_version(path: str | None = None) -> str:
    """Stable version of the membership source = sha256 of the raw file bytes."""
    import hashlib
    p = path or DEFAULT_MEMBERSHIP_PATH
    if not os.path.exists(p):
        raise FileNotFoundError(
            f"PIT membership file missing: {p} — no silent fallback universe.")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _renames(path: str) -> list[dict]:
    """Rename chain as [{old, new, effective_date}]. Missing file -> [] (no renames)."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        doc = json.load(f)
    inner = doc.get("renames", []) if isinstance(doc, dict) else []
    out = []
    for e in inner if isinstance(inner, list) else []:
        if isinstance(e, dict) and e.get("old") and e.get("new"):
            out.append({"old": e["old"], "new": e["new"],
                        "effective_date": (e.get("effective_date") or "")[:10]})
    return out


def _canonical(sym: str, date_iso: str, renames: list[dict]) -> str:
    """Date-aware rename: old -> new once effective_date <= as-of date."""
    for e in renames:
        if sym == e["old"] and e["effective_date"] and e["effective_date"] <= date_iso[:10]:
            return e["new"]
    return sym


def members_at(index_id: str, date_iso: str, strict: bool = True,
               path: str | None = None, renames_path: str | None = None) -> tuple[list[str], dict]:
    """Symbols member on date_iso (inclusive both ends). Returns (sorted symbols,
    meta) where meta records weak-row counts for disclosure. Raw NSE symbols
    (no .NS suffix — caller adds it per panel convention)."""
    rows = _read_rows(path or DEFAULT_MEMBERSHIP_PATH)
    ren = _renames(renames_path or DEFAULT_RENAMES_PATH)
    d = date_iso[:10]
    out, weak = set(), 0
    for r in rows:
        if r.get("index_id") != index_id:
            continue
        src = (r.get("source") or "").strip()
        if src not in STRICT_SOURCES:
            if strict:
                continue
            weak += 1
        frm, to = (r.get("valid_from") or "")[:10], (r.get("valid_to") or "")[:10] or _OPEN
        if frm <= d <= to:
            out.add(_canonical(r["symbol"], d, ren))
    return sorted(out), {"weak_rows_included": 0 if strict else weak, "strict": strict}


def to_ns_tickers(symbols: list[str]) -> list[str]:
    """Panel convention: verbatim symbol + '.NS' (matches nifty500.txt: M&M.NS)."""
    return sorted({s + ".NS" for s in symbols})


def start_date_universe(index_id: str, start_iso: str, strict: bool = True,
                        path: str | None = None,
                        renames_path: str | None = None) -> tuple[list[str], dict]:
    """Step-1 deliverable: members as of the window START (prereg §2).

    Removes future joiners; keeps mid-window exits on full series (residual
    bias disclosed UP). Full time-varying membership = v5 future work.
    """
    syms, meta = members_at(index_id, start_iso, strict, path, renames_path)
    meta = dict(meta, index_id=index_id, start=start_iso[:10], attribution=ATTRIBUTION)
    return to_ns_tickers(syms), meta
