"""Lineage: parent-child links between hypotheses/strategies (§7)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import sqlite_conn
from app.research_memory import store as ST


def link(child_fp: str, parent_fp: str, relation: str = "mutated-from") -> None:
    ST.init_tables()
    sqlite_conn().execute(
        "INSERT OR REPLACE INTO research_lineage(child_fp, parent_fp, relation, ts)"
        " VALUES (?,?,?,?)",
        (child_fp, parent_fp, relation,
         datetime.now(timezone.utc).isoformat()))
    sqlite_conn().commit()


def children(parent_fp: str) -> list[dict]:
    ST.init_tables()
    rows = sqlite_conn().execute(
        "SELECT child_fp, parent_fp, relation, ts FROM research_lineage"
        " WHERE parent_fp=? ORDER BY ts", (parent_fp,)).fetchall()
    return [{"child": r[0], "parent": r[1], "relation": r[2], "ts": r[3]} for r in rows]


def tree(root_fp: str, depth: int = 4) -> dict:
    """Nested family tree (demo artifact shape: F1 -> F9 -> F14/F18)."""
    node: dict = {"fp": root_fp, "children": []}
    if depth <= 0:
        return node
    for c in children(root_fp):
        node["children"].append(tree(c["child"], depth - 1))
    return node
