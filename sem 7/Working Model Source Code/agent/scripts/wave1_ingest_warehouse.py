"""W1 real-data ingestion + coverage/rights artifacts.

Ingests the audited local archives (read-only) into the research warehouse DB
and writes ``reports/alpha_v3_1/pit_source_integrity.json``. Prints a summary
for ``historical_nse_data_coverage_and_rights.md``. No network, no mutation of
source files; the warehouse itself is derived, rebuildable data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend-extension"))

from quantplus_intelligence.research_v3 import warehouse as W  # noqa: E402

REPORTS = REPO / "reports" / "alpha_v3_1"


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    db_path = REPO / "backend-extension" / "data" / "research_v3" / "warehouse.sqlite3"
    conn = W.connect(str(db_path))

    print(f"warehouse: {db_path}")
    print("ingesting official bhavcopy (5.2M rows, streaming)...")
    bhav = W.ingest_bhavcopy(conn)
    print(f"  rows={bhav['rows_ingested']} dups={bhav['rows_ignored_duplicates']} "
          f"sha256={bhav['source_sha256'][:16]}")

    mem = W.ingest_membership(conn)
    print(f"membership: rows={mem['rows_ingested']} "
          f"malformed={mem.get('malformed_rows_excluded', 0)} sha256={mem['source_sha256'][:16]}")

    tri = W.ingest_nifty50_tri(conn)
    print(f"nifty50 TRI: rows={tri['rows_ingested']} sha256={tri['source_sha256'][:16]}")

    fees = W.ingest_fee_schedules(conn)
    print(f"fee schedules mirrored: {fees['rows']} rows")

    # coverage + integrity artifacts
    cov = W.coverage_report(conn)
    nifty50_2020 = W.members_at(conn, "nifty50", "2020-01-01")
    panel_probe = W.panel_asof(conn, "nifty50", "2020-01-01")
    integrity = {
        "generated_at": cov["generated_at"],
        "warehouse_db": str(db_path),
        "sources": {
            "nse_eod_bhavcopy_2015_2026_full": {
                "path": W.BHAVCOPY_PATH,
                "sha256": bhav["source_sha256"],
                "rows": bhav["rows_ingested"],
                "source_class": W.SOURCE_CLASS_BHAVCOPY,
                "archive_built_on": W.BHAVCOPY_ARCHIVE_BUILT_ON,
                "provenance_note": W.RETROSPECTIVE_NOTE,
            },
            "nse_index_membership_history": {
                "path": W.MEMBERSHIP_PATH,
                "sha256": mem["source_sha256"],
                "rows": mem["rows_ingested"],
                "attribution": W.ATTRIBUTION_MEMBERSHIP,
                "source_class": "PRESS_RELEASE_RECONSTRUCTION",
                "renames": {
                    "path": W.RENAMES_PATH,
                    "rows_ingested": mem.get("renames_ingested"),
                    "undated_rows": mem.get("renames_undated"),
                    "invalid_date_strings": mem.get("renames_invalid_date_strings"),
                    "policy": "undated / placeholder effective dates join "
                              "instrument identity (alias set) but never change "
                              "display naming and never mirror a verified "
                              "corporate action (fail closed on dates)",
                },
            },
            "nifty50_tri_history": {
                "path": W.NIFTY50_TRI_PATH,
                "sha256": tri["source_sha256"],
                "rows": tri["rows_ingested"],
                "source_class": "OFFICIAL_EXCHANGE_RECORD",
            },
        },
        "coverage": cov,
        "pit_probes": {
            "nifty50_members_at_2020_01_01": {
                "status": nifty50_2020.status, "n_members": len(nifty50_2020.rows),
                "weak_rows_included": nifty50_2020.meta.get("weak_rows_included"),
            },
            "panel_asof_2020_01_01": {
                "status": panel_probe.status,
                "n_with_bars": len(panel_probe.rows),
                "n_excluded_no_bars": panel_probe.meta.get("n_excluded_no_bars"),
                "excluded_sample": panel_probe.meta.get("excluded_no_bars", [])[:10],
            },
        },
        "claim": "source hashes recorded pre-ingestion; warehouse derived from "
                 "immutable archives; no source file was edited",
    }
    out = REPORTS / "pit_source_integrity.json"
    out.write_text(json.dumps(integrity, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(cov["sessions_per_year"], indent=2))
    print(f"distinct symbols: {cov['distinct_symbols']}")
    print(f"known gaps: {json.dumps(cov['known_gaps'], indent=2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
