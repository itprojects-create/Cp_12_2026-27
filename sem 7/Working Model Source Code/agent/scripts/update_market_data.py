"""Daily market-data updater (§50): orchestrated post-close sequence.

Order: equity EOD -> delivery(implicit in full bhav) -> indices/VIX ->
bulk/block -> FII/DII -> F&O -> announcements -> corporate actions ->
filings/shareholding(manual-first, skipped live) . --settlement runs only the
post-settlement group. Each step is independent: one dataset's failure never
aborts the rest (statuses aggregated, exit code reflects worst).

Usage:
  python scripts/update_market_data.py [--day YYYY-MM-DD] [--settlement]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_acquisition import base as B  # noqa: E402
from app.data_acquisition.nse import announcements as NA  # noqa: E402
from app.data_acquisition.nse import corporate_actions as NCA  # noqa: E402
from app.data_acquisition.nse import deals as D  # noqa: E402
from app.data_acquisition.nse import equity as E  # noqa: E402
from app.data_acquisition.nse import fno as F  # noqa: E402
from app.data_acquisition.nse import indices as I  # noqa: E402
from app.data_acquisition.nse import institutional as N  # noqa: E402


def _watchlist() -> list[str]:
    try:
        from app.core.trend_core import UNIVERSE
        return sorted(UNIVERSE)
    except ImportError:
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--settlement", action="store_true")
    a = ap.parse_args()
    day = a.day or datetime.now(timezone.utc).date().isoformat()
    steps: list[tuple[str, object]] = []
    if not a.settlement:
        steps += [("equity-eod", lambda: E.NseEquityEod().fetch(days=[day])),
                  ("indices", lambda: I.NseIndices().fetch(days=[day]))]
    steps += [("bulk-block-deals", lambda: D.NseDeals().fetch(days=[day])),
              ("fii-dii-provisional", lambda: N.NseFlows().fetch(day=day)),
              ("fno-bhavcopy", lambda: F.NseFno().fetch(days=[day])),
              ("announcements", lambda: NA.NseAnnouncements().fetch(
                  symbols=_watchlist() or ["RELIANCE.NS"], day=day)),
              ("corporate-actions", lambda: NCA.NseCorporateActions().fetch(
                  symbols=_watchlist() or ["RELIANCE.NS"], day=day))]
    results = {}
    for name, fn in steps:
        try:
            r = fn()
            results[name] = {"status": r.status.value, "received": r.records_received,
                             "written": r.records_written}
        except Exception as e:  # noqa: BLE001 - independent steps, never abort all
            results[name] = {"status": "ERROR", "note": f"{type(e).__name__}: {e}"[:200]}
            B.log_error("updater", name, day, "ERROR", str(e)[:200])
    print(json.dumps({"day": day, "settlement_only": a.settlement,
                      "results": results}, indent=2))
    bad = [k for k, v in results.items() if v["status"] not in ("SUCCESS",)]
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
