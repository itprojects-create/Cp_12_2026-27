"""Partitioned parquet writer for normalized tabular data (§§85–86).

Layout data/normalized/<dataset>/YYYY-MM.parquet (month grain — no millions
of tiny files). Writes are upserts on natural keys: read existing partition,
concat, drop duplicates keeping latest, atomic rewrite. Raw evidence always
stays in data/raw (never replaced).
"""
from __future__ import annotations

import os
import tempfile

NORMALIZED_ROOT = os.environ.get("DATA_NORMALIZED_ROOT",
                                 os.path.join("data", "normalized"))


def month_path(dataset: str, yyyy_mm: str) -> str:
    return os.path.join(NORMALIZED_ROOT, dataset, f"{yyyy_mm}.parquet")


def upsert(dataset: str, yyyy_mm: str, df, keys: list[str]) -> dict:
    """Upsert rows into the month partition. Returns {path, rows, added}."""
    import pandas as pd
    path = month_path(dataset, yyyy_mm)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    before = 0
    if os.path.exists(path):
        old = pd.read_parquet(path)
        before = len(old)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            df.to_parquet(f, index=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"path": path, "rows": len(df), "added": len(df) - before}


def read_month(dataset: str, yyyy_mm: str):
    import pandas as pd
    path = month_path(dataset, yyyy_mm)
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_parquet(path)
