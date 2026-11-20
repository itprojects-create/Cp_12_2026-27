"""Research calibration CLI (§77): report + per-role value table.

Today: INSUFFICIENT_CALIBRATION_SAMPLE (no mature forward outcomes yet) with
exact counts — plumbing proof, not a quality claim.

Usage: python scripts/research_calibration.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.research import calibration as CAL  # noqa: E402


def main() -> None:
    print(json.dumps({"calibration": CAL.calibration_report(),
                      "roles": CAL.role_value_metrics()}, indent=2))


if __name__ == "__main__":
    main()
