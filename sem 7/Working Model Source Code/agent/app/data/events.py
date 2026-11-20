"""Event diet: earnings (reported surprise + scheduled), corporate actions — all PIT-filtered.

PIT rules (explicit, auditable):
- Reported earnings/dividends/splits are usable iff event_date <= as_of (they occurred).
- Scheduled earnings are typically announced ~3 weeks prior; an upcoming result is
  usable iff as_of >= event_date - 21d (assumption, flagged on the item). Otherwise
  the future date itself would leak information not yet known at as_of.
- Cached raw frames on disk; PIT filtering applied on every read.

NOT available via free APIs (honest gaps, stubbed for a future broker plug-in):
FII/DII flows, delivery %, NSE option-chain OI/IV. See NotConfigured below.
"""
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

CACHE_DIR = "data/events_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
ANNOUNCE_WINDOW_DAYS = 21  # assumed pre-announcement window for scheduled results

class NotConfigured(RuntimeError):
    """Raised by data sources with no free-API implementation. Plug a broker feed here."""

@dataclass
class EventItem:
    kind: str            # earnings_reported | earnings_upcoming | dividend | split
    date: str            # ISO date of the event
    known_at: str        # ISO datetime from which the agent may use it (PIT stamp)
    summary: str         # one-line human text, pre-truncated
    surprise_pct: float | None = None
    assumed: bool = False  # True iff known_at rests on the 21-day announcement assumption

def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _asof_key(as_of: datetime) -> str:
    return _utc(as_of).date().isoformat()

class YFinanceEventsProvider:
    name = "yfinance-events"

    def _raw(self, instrument: str, as_of: datetime) -> dict:
        key = f"{CACHE_DIR}/{instrument.replace('.', '_')}_{_asof_key(as_of)}.json"
        if os.path.exists(key):
            with open(key, encoding="utf-8") as f:
                cached = json.load(f)
                # Back-compat: pre-Day1 caches lack fetched_at / revision flag.
                # Treat surprise_pct as revised (current-table), never as-filed.
                if isinstance(cached, dict) and "earn" in cached:
                    return cached
        import yfinance as yf
        import pandas as pd
        t = yf.Ticker(instrument)
        fetched_at = datetime.now(timezone.utc).isoformat()
        raw: dict = {"earn": [], "div": [], "split": [], "fetched_at": fetched_at,
                     "revision_note": ("yfinance earnings table is current-revised, not as-filed; "
                                       "surprise_pct is indicative, not PIT-guaranteed")}
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                for ts, row in ed.iterrows():
                    d = pd.Timestamp(ts)
                    raw["earn"].append({
                        "date": d.date().isoformat(),
                        "est": _num(row.get("EPS Estimate")),
                        "rep": _num(row.get("Reported EPS")),
                        "sur": _num(row.get("Surprise(%)"))})
        except Exception:
            pass
        for attr, dest in (("dividends", "div"), ("splits", "split")):
            try:
                s = getattr(t, attr)
                if s is not None and len(s):
                    for ts, v in s.items():
                        raw[dest].append({"date": pd.Timestamp(ts).date().isoformat(),
                                          "value": float(v)})
            except Exception:
                pass
        with open(key, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        return raw

    def events(self, instrument: str, as_of: datetime, lookback_days: int = 120,
               upcoming_days: int = 45) -> list[EventItem]:
        as_of_u = _utc(as_of)
        as_of_d = as_of_u.date().isoformat()
        raw = self._raw(instrument, as_of)
        out: list[EventItem] = []
        for e in raw.get("earn", []):
            if e["date"] <= as_of_d and e["rep"] is not None:
                sur = e["sur"]
                if sur is None and e["est"]:
                    sur = round((e["rep"] / e["est"] - 1) * 100, 1)
                # Revision caveat: surprise comes from the current-revised table.
                # Dates are stable; magnitudes are indicative. Large surprises still
                # carry drift signal, but never treat bps as exact as-filed.
                out.append(EventItem("earnings_reported", e["date"], e["date"] + "T00:00:00+00:00",
                                     f"reported EPS {e['rep']} vs est {e['est']} "
                                     f"({sur:+.1f}% surprise, revised-table indicative)" if sur is not None else
                                     f"reported EPS {e['rep']} (revised-table)", sur))
            elif as_of_d < e["date"] <= (as_of_u + timedelta(days=upcoming_days)).date().isoformat():
                known = (datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
                         - timedelta(days=ANNOUNCE_WINDOW_DAYS))
                if known <= as_of_u:  # schedule plausibly known at as_of
                    out.append(EventItem("earnings_upcoming", e["date"], known.isoformat(),
                                         f"results due {e['date']} (est EPS {e['est']})",
                                         assumed=True))
        cutoff = (as_of_u - timedelta(days=lookback_days)).date().isoformat()
        for d in raw.get("div", []):
            if cutoff <= d["date"] <= as_of_d:
                out.append(EventItem("dividend", d["date"], d["date"] + "T00:00:00+00:00",
                                     f"dividend {d['value']}"))
        for s in raw.get("split", []):
            if cutoff <= s["date"] <= as_of_d:
                out.append(EventItem("split", s["date"], s["date"] + "T00:00:00+00:00",
                                     f"split {s['value']}:1"))
        out.sort(key=lambda x: x.date)
        return out

    # --- broker-only feeds: explicit stubs, no silent fakes ---
    def fii_dii_flows(self, *a, **k):
        raise NotConfigured("FII/DII flows need a broker/NSE feed (no reliable free API)")
    def delivery_pct(self, *a, **k):
        raise NotConfigured("delivery % needs NSE archival feed (no reliable free API)")
    def option_chain(self, *a, **k):
        raise NotConfigured("NSE option chain needs a broker feed (Yahoo has no NSE options)")

def _num(x) -> float | None:
    try:
        import math
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None

def events_brief(items: list[EventItem]) -> str:
    if not items:
        return "(no corporate events in window)"
    return "\n".join(f"- [{e.date}{' *assumed-schedule' if e.assumed else ''}] {e.kind}: {e.summary}"
                     for e in items[-8:])
