"""Default-off local host wrapper for the Wave 6 worker health endpoint.

No deployment, provider fetch, webhook delivery, or broker call is performed by
this script. `--health-once` is read-only. `--serve-health` binds localhost and
requires QUANTPLUS_W6_ENABLED=true; it is a later-hosting building block, not an
always-on claim.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3.forward.ledger import ForwardLedger
from quantplus_intelligence.research_v3.wave6 import health_endpoint


def build_health_payload(ledger_path: str | Path, *, now_utc: str | None = None) -> dict:
    ledger = ForwardLedger(ledger_path)
    return health_endpoint(
        ledger, None,
        now_utc=now_utc or datetime.now(timezone.utc).isoformat())


def serve(ledger_path: Path, host: str, port: int) -> None:
    if os.environ.get("QUANTPLUS_W6_ENABLED", "").lower() != "true":
        raise RuntimeError("W6_DISABLED: set QUANTPLUS_W6_ENABLED=true only after operator approval")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib HTTP contract
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(build_health_payload(ledger_path), sort_keys=True).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            del format, args  # no request data or secrets in default logs

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--health-once", action="store_true")
    parser.add_argument("--serve-health", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.health_once:
        print(json.dumps(build_health_payload(args.ledger), indent=2, sort_keys=True))
        return
    if args.serve_health:
        serve(Path(args.ledger), args.host, args.port)
        return
    raise SystemExit("choose --health-once or --serve-health")


if __name__ == "__main__":
    main()
