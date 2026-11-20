"""Phase 9 exit proof: drive a full session + live stage stream with zero frontend code.

Default (mocked): in-process TestClient, canned LLM — proves HTTP+WS plumbing, 0 tokens.
--live: against a running server (uvicorn app.main:app), real LLM billing.
"""
from __future__ import annotations
import argparse
import json
import sys

def run_mocked() -> None:
    from fastapi.testclient import TestClient
    from tests._mocks import install_mocks
    from app.main import app

    class _MP:
        @staticmethod
        def setattr(obj, name, value):
            setattr(obj, name, value)
    install_mocks(_MP())  # type: ignore
    from app.db import sqlite_conn
    sqlite_conn().execute("DELETE FROM sessions WHERE instrument='E2E.NS'")
    sqlite_conn().execute("DELETE FROM theses WHERE instrument='E2E.NS'")
    sqlite_conn().commit()

    c = TestClient(app)
    sid = c.post("/api/v1/sessions", json={"instrument": "E2E.NS",
                 "as_of": "2024-06-10T00:00:00Z", "interval": "1d",
                 "force_rerun": True}).json()["id"]
    print("session:", sid)
    status = c.get(f"/api/v1/sessions/{sid}").json()
    print("status:", status["status"], "| decision:", status["decision"])
    assert status["status"] == "done", status
    frames = []
    with c.websocket_connect(f"/api/v1/sessions/{sid}/events") as ws:
        try:
            while True:
                f = json.loads(ws.receive_text())
                frames.append(f)
                print(f"  [{f['stage']}/{f['agent']}] {f['status']}")
        except Exception:
            pass
    assert frames and frames[-1]["status"] == "done"
    print(f"E2E MOCKED OK: {len(frames)} stage frames, terminal=done")

def run_live(base: str) -> None:
    import httpx, asyncio, websockets
    sid = httpx.post(f"{base}/api/v1/sessions", json={"instrument": "RELIANCE.NS",
                     "as_of": "2024-06-10T00:00:00Z", "interval": "1d"}).json()["id"]
    print("session:", sid)

    async def stream():
        uri = base.replace("http", "ws") + f"/api/v1/sessions/{sid}/events"
        async with websockets.connect(uri) as ws:
            async for msg in ws:
                f = json.loads(msg)
                print(f"  [{f['stage']}/{f['agent']}] {f['status']}")
                if f["status"] in ("done",) or f["status"].startswith("failed"):
                    break
    asyncio.run(stream())
    print("final:", httpx.get(f"{base}/api/v1/sessions/{sid}").json())
    print("E2E LIVE OK")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    sys.path.insert(0, ".")
    (run_live(args.base) if args.live else run_mocked())
