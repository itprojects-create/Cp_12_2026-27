from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.api.stocks import website_auth
from app.config import settings
from app.data import fyers_auth
import logging


class CallbackLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn ordinarily logs the entire callback URL, including auth_code.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].split("?", 1)[0] in ("/api/v1/fyers/callback", "/fyers/callback"):
                args[2] = args[2].split("?", 1)[0]
                record.args = tuple(args)
        return True

router = APIRouter(prefix="/api/v1/fyers")


@router.get("/status", dependencies=[Depends(website_auth)])
def status():
    from app.data.fyers_provider import fyers
    from app.data.live_market import market
    token = fyers_auth.stored_token()
    expiry = fyers_auth.jwt_expiry(token.split(":", 1)[-1]) if token else None
    return {"app_configured": bool(settings.FYERS_CLIENT_ID and settings.FYERS_SECRET_KEY),
            "authenticated": bool(fyers.token()), "connected": market.connected,
            "login_required": not bool(fyers.token()),
            "expires_at": datetime.fromtimestamp(expiry, timezone.utc).isoformat() if expiry else None}


@router.get("/callback", response_class=HTMLResponse)
async def callback(auth_code: str = "", state: str = ""):
    try:
        await fyers_auth.complete_authorization(auth_code, state)
    except ValueError:
        raise HTTPException(400, "Fyers login could not complete. Generate a fresh login link and check the registered redirect URL.")
    except Exception:
        raise HTTPException(502, "Fyers token service unavailable. Generate a fresh login link and retry.")
    from app.data.live_market import market
    await market.refresh_fyers_connection()
    return HTMLResponse("<html><head><title>Fyers connected</title></head><body>"
                        "<h1>Fyers connected</h1><p>Your market-data token is saved. "
                        "Return to Quant Plus and refresh the stock page.</p></body></html>", headers={
                            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
