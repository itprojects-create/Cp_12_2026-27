"""Operator helper. Prints a login URL, never prints tokens or the app secret."""
import argparse
import asyncio
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data.fyers_auth import start_authorization, complete_authorization

parser = argparse.ArgumentParser(description="Connect the website's Fyers market-data account")
parser.add_argument("--redirect-uri", help="Exact redirect URL registered for this app")
parser.add_argument("--open", action="store_true", help="Open the login page in your browser")
parser.add_argument("--complete-url", help="Full redirected URL if using an external redirect page")
args = parser.parse_args()
try:
    if args.complete_url:
        query = parse_qs(urlsplit(args.complete_url).query)
        asyncio.run(complete_authorization(query.get("auth_code", [""])[0], query.get("state", [""])[0]))
        print("Fyers token stored. Open or refresh a stock page to connect the feed.")
    else:
        url = start_authorization(args.redirect_uri)
        print(url)
        if args.open:
            webbrowser.open(url)
except Exception:
    print("Connection could not complete. Verify the registered redirect URL and generate a fresh login link.", file=sys.stderr)
    sys.exit(1)
