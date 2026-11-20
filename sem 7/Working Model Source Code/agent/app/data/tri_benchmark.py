"""Official NSE total-return benchmarks (prereg_model_data_wiring.md Step 3).

Replaces hand-rolled bench math in NEW reports only (old JSONs keep theirs).
Source: NSE TRI histories (vendored upstream, NEVER edited). Handles
reverse-chrono order + "17 Sep 2026" format; ascending sort, date dedupe
(keep last), T+1 join (value at last date <= query date). Missing file or
uncovered window -> loud error, never synthetic benchmark.
"""
from __future__ import annotations

import os
from datetime import datetime

_TRI_PATHS = {
    "NIFTY50": os.environ.get("NIFTY50_TRI_PATH")
    or r"D:\Model\NEW DATA\nifty50_tri_history.csv",
    "MOMENTUM30": os.environ.get("MOMENTUM30_TRI_PATH")
    or r"D:\Model\NEW DATA\nifty200_momentum30_tri_history.csv",
}


def _load(path: str) -> list[tuple[str, float]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"TRI history missing: {path} — no synthetic benchmark.")
    import pandas as pd
    df = pd.read_csv(path)
    if set(df.columns) != {"date", "index_name", "total_returns_index"} and \
            list(df.columns) != ["date", "index_name", "total_returns_index"]:
        raise ValueError(f"unexpected TRI schema: {list(df.columns)}")
    dates = pd.to_datetime(df["date"], format="%d %b %Y", errors="coerce")
    if dates.isna().any():
        raise ValueError("unparseable TRI dates present")
    vals = df["total_returns_index"].astype(float)
    pts = sorted(zip(dates.dt.strftime("%Y-%m-%d"), vals), key=lambda p: p[0])
    out: list[tuple[str, float]] = []
    for d, v in pts:
        if out and out[-1][0] == d:
            out[-1] = (d, v)  # dedupe: keep last
        else:
            out.append((d, v))
    if not out:
        raise ValueError("empty TRI series")
    return out


def _at_or_before(pts: list[tuple[str, float]], date_iso: str) -> float:
    d = date_iso[:10]
    best = None
    for dd, v in pts:
        if dd <= d:
            best = v
        else:
            break
    if best is None:
        raise ValueError(f"TRI uncovered before {d}")
    return best


def total_return(index: str = "NIFTY50", start_iso: str = "", end_iso: str = "",
                 path: str | None = None) -> dict:
    """Official TRI total return / CAGR over [start, end] (T+1 join both ends)."""
    resolved = DEFAULT_TRI_paths(index)  # validate index BEFORE path short-circuit
    pts = _load(path or resolved)
    v0 = _at_or_before(pts, start_iso)
    v1 = _at_or_before(pts, end_iso)
    years = (datetime.fromisoformat(end_iso[:10]) - datetime.fromisoformat(start_iso[:10])).days / 365.25
    total = v1 / v0 - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    return {"index": index, "start": start_iso[:10], "end": end_iso[:10],
            "total": round(total, 4), "cagr": round(cagr, 4),
            "source": "NSE TRI history (vendored upstream)"}


def DEFAULT_TRI_paths(index: str) -> str:
    try:
        return _TRI_PATHS[index]
    except KeyError:
        raise ValueError(f"unknown TRI index {index!r}") from None
