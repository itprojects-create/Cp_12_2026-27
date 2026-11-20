"""Freeze strategy/config for forward runs (P8, §55).

Usage:
  python scripts/freeze_strategy.py [--out data/strategy_freeze_<date>.json]
  python scripts/freeze_strategy.py --verify data/strategy_freeze_2026-10-10.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.governance import freeze as FRZ  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--verify", default=None)
    a = ap.parse_args()
    if a.verify:
        rec = FRZ.verify(a.verify)
        print(json.dumps(rec, indent=2))
        sys.exit(0 if rec["verdict"] == "MATCH" else 3)
    rec = FRZ.freeze(a.out)
    print(json.dumps({"path": rec["path"],
                      "freeze": rec["freeze"]["freeze_version"],
                      "config_hash": rec["freeze"]["effective_config"]["config_hash"]},
                     indent=2))


if __name__ == "__main__":
    main()
