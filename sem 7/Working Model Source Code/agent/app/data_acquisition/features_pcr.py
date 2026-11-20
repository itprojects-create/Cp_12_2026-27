"""PCR feature definitions (§32): deterministic, versioned, contract-level.

Never scraped. Each variant encodes expiry inclusion, strike inclusion,
underlying universe, and timestamp. Computed from normalized contract rows
(symbol/expiry/instrument_type/option_type/open_interest/volume).
"""
from __future__ import annotations

VERSION = "PCR_DEFS_V1"

DEFINITIONS = {
    "PCR_OI_ALL": {"numerator": "put OI, all expiries/strikes",
                   "denominator": "call OI, all expiries/strikes",
                   "expiry_inclusion": "all", "strike_inclusion": "all",
                   "universe": "index", "timestamp": "eod"},
    "PCR_OI_NEAR_EXPIRY": {"numerator": "put OI, nearest expiry only",
                           "denominator": "call OI, nearest expiry only",
                           "expiry_inclusion": "nearest", "strike_inclusion": "all",
                           "universe": "index", "timestamp": "eod"},
    "PCR_VOLUME_ALL": {"numerator": "put volume, all expiries/strikes",
                       "denominator": "call volume, all expiries/strikes",
                       "expiry_inclusion": "all", "strike_inclusion": "all",
                       "universe": "index", "timestamp": "eod"},
}


def compute(rows: list[dict], underlying: str = "NIFTY",
            day_iso: str = "") -> dict:
    """rows: normalized contract dicts. Returns variant values + definition
    version. Zero denominators -> None (never inf, never imputed)."""
    idx = [r for r in rows if (r.get("symbol") or "").upper() == underlying.upper()]
    fut = [r for r in idx if (r.get("instrument_type") or "") in ("FUTIDX", "FUTSTK")]
    calls = [r for r in idx if (r.get("option_type") or "") == "CE"]
    puts = [r for r in idx if (r.get("option_type") or "") == "PE"]

    def _sum(rs, field):
        return sum(float(r.get(field) or 0) for r in rs)

    expiries = sorted({r.get("expiry") for r in idx if r.get("expiry")})
    near = expiries[0] if expiries else None
    near_calls = [r for r in calls if r.get("expiry") == near]
    near_puts = [r for r in puts if r.get("expiry") == near]

    def _ratio(num, den):
        return (num / den) if den else None

    return {"day": day_iso, "underlying": underlying,
            "definition_version": VERSION,
            "PCR_OI_ALL": _ratio(_sum(puts, "open_interest"), _sum(calls, "open_interest")),
            "PCR_OI_NEAR_EXPIRY": _ratio(_sum(near_puts, "open_interest"),
                                         _sum(near_calls, "open_interest")),
            "PCR_VOLUME_ALL": _ratio(_sum(puts, "volume"), _sum(calls, "volume")),
            "n_contracts": len(idx), "n_futures": len(fut),
            "nearest_expiry": near}
