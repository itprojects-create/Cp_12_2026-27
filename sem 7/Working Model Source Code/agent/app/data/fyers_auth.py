"""Operator-initiated FYERS OAuth; credentials and tokens never reach the UI."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from app.config import settings

PRIVATE_ROOT = Path(__file__).resolve().parents[2] / "data" / "fyers_private"
_state_lock = threading.Lock()


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def jwt_expiry(token: str) -> float | None:
    # Informational expiry only. Trust/authorization is checked by FYERS itself.
    try:
        raw = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return float(payload["exp"])
    except (IndexError, KeyError, ValueError, TypeError):
        return None


def stored_token() -> str:
    try:
        data = json.loads((PRIVATE_ROOT / "tokens.json").read_text(encoding="utf-8"))
        if data.get("client_id") == settings.FYERS_CLIENT_ID:
            return str(data.get("access_token", ""))
    except (OSError, ValueError):
        pass
    return settings.FYERS_ACCESS_TOKEN


def access_token() -> str:
    value = stored_token()
    if not value:
        return ""
    raw = value.split(":", 1)[-1]
    expiry = jwt_expiry(raw)
    if expiry is not None and expiry <= time.time() + 30:
        return ""
    if ":" in value:
        return value
    return f"{settings.FYERS_CLIENT_ID}:{value}" if settings.FYERS_CLIENT_ID else ""


def start_authorization(redirect_uri: str | None = None) -> str:
    redirect_uri = redirect_uri or settings.FYERS_REDIRECT_URI
    if not settings.FYERS_CLIENT_ID or not settings.FYERS_SECRET_KEY or not redirect_uri:
        raise ValueError("Configure FYERS_CLIENT_ID, FYERS_SECRET_KEY and the registered FYERS_REDIRECT_URI")
    state = secrets.token_urlsafe(32)
    with _state_lock:
        atomic_json(PRIVATE_ROOT / "authorization.json", {
            "state_hash": hashlib.sha256(state.encode()).hexdigest(),
            "expires_at": time.time() + 1800,
            "client_id": settings.FYERS_CLIENT_ID,
        })
    return "https://api-t1.fyers.in/api/v3/generate-authcode?" + urlencode({
        "client_id": settings.FYERS_CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "state": state})


async def complete_authorization(code: str, state: str):
    if not code or not state:
        raise ValueError("Missing authorization code or state")
    path = PRIVATE_ROOT / "authorization.json"
    with _state_lock:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("No pending Fyers login; generate a fresh login link")
        if (saved.get("expires_at", 0) < time.time() or
                saved.get("client_id") != settings.FYERS_CLIENT_ID or
                not secrets.compare_digest(saved.get("state_hash", ""), hashlib.sha256(state.encode()).hexdigest())):
            raise ValueError("Expired or invalid login state; generate a fresh login link")
        path.unlink()  # Single-use before exchanging: concurrent callbacks cannot replay it.
    app_hash = hashlib.sha256(f"{settings.FYERS_CLIENT_ID}:{settings.FYERS_SECRET_KEY}".encode()).hexdigest()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("https://api-t1.fyers.in/api/v3/validate-authcode", json={
            "grant_type": "authorization_code", "appIdHash": app_hash, "code": code})
        response.raise_for_status()
        data = response.json()
    if data.get("s") != "ok" or not data.get("access_token"):
        raise ValueError("Fyers rejected the authorization code; generate a fresh login link")
    atomic_json(PRIVATE_ROOT / "tokens.json", {
        "client_id": settings.FYERS_CLIENT_ID, "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""), "saved_at": time.time(),
    })
