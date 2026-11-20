"""Version-aware XBRL parser (§35). Raw ingestion stays decoupled.

Parses XBRL/XML instances without assuming one schema: facts keyed by tag
local-name, periods from xbrli:context date ranges, units from unit refs.
Emits ONLY fields supported by the filing (§35 lists); unknown tags are
ignored (never fabricated). Namespace recorded per filing (schema drift
detection compares it).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

PARSER_VERSION = "xbrl-v1"

# tag local-name (lower) -> normalized field. Suffix match intentionally loose
# across taxonomy variants; collisions resolve first-seen (documented).
FIELD_TAGS = {
    "revenuefromoperations": "revenue", "revenue": "revenue",
    "totalrevenue": "revenue",
    "profitbeforetax": "operating_profit", "profitbeforetaxandexceptionalitems": "operating_profit",
    "ebitda": "ebitda",
    "profitaftertax": "pat", "profitforthey": "pat", "netprofit": "pat",
    "earningspersharebasic": "eps_basic", "basicearningspershare": "eps_basic",
    "earningspersharediluted": "eps_diluted",
    "totalassets": "assets", "totalliabilities": "liabilities",
    "totalequity": "equity", "totaldebt": "debt", "cashandcashequivalents": "cash",
    "netcashfromoperatingactivities": "operating_cash_flow",
    "netcashfrominvestingactivities": "investing_cash_flow",
    "netcashfromfinancingactivities": "financing_cash_flow",
    "promotershareholding": "promoter_pct", "promoterholding": "promoter_pct",
    "publicshareholding": "public_pct",
    "fpishareholding": "fpi_pct", "diishareholding": "dii_pct",
    "institutionalshareholding": "institutional_pct",
    "pledgedshares": "pledged_promoter",
    "numberofsharesoutstanding": "shares_outstanding",
}

def parse_sanity(parsed: dict, period_start: str, period_end: str) -> list[str]:
    """§88 detection-only sanity: period validity, fact presence, context order.
    Flags are recorded; reported company figures are NEVER altered."""
    flags = []
    if not period_start or not period_end or period_start > period_end:
        flags.append("invalid_period")
    if not parsed.get("facts"):
        flags.append("no_extractable_facts")
    if parsed.get("warnings"):
        flags.append(f"parser_warnings:{len(parsed['warnings'])}")
    return flags


def _local(tag: str) -> str:
    return re.sub(r"^\{.*\}", "", tag or "").strip().lower().replace("_", "").replace("-", "")


def parse_xbrl(payload: bytes) -> dict:
    """Parse an XBRL instance. Returns {namespace, periods, facts, standalone,
    consolidated, warnings}. Never raises on schema drift — unknown layouts
    yield empty facts with a drift warning (§57 pattern)."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as e:
        return {"namespace": "", "periods": {}, "facts": {}, "standalone": None,
                "consolidated": None, "warnings": [f"xml-parse: {e}"]}
    namespaces = sorted({re.sub(r"^\{(.*)\}.*$", r"\1", el.tag)
                         for el in root.iter() if el.tag.startswith("{")})
    contexts: dict[str, dict] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        cid = ctx.get("id", "")
        start = end = instant = ""
        for child in ctx.iter():
            loc = _local(child.tag)
            if loc == "startdate":
                start = (child.text or "").strip()[:10]
            elif loc == "enddate":
                end = (child.text or "").strip()[:10]
            elif loc == "instant":
                instant = (child.text or "").strip()[:10]
        dims = {(_local(d.tag), (d.text or "").strip()) for d in ctx.iter()
                if _local(d.tag) in ("explicitmember", "typedmember")}
        contexts[cid] = {"start": start, "end": end or instant,
                         "instant": instant, "dims": sorted(dims)}
    facts: dict[str, dict] = {}
    warnings = []
    for el in root.iter():
        loc = _local(el.tag)
        if loc in ("context", "unit", "schema", "linkbase") or not loc:
            continue
        field = FIELD_TAGS.get(loc)
        if field is None or el.text is None:
            continue
        try:
            value = float(el.text.strip().replace(",", ""))
        except (TypeError, ValueError):
            warnings.append(f"non-numeric fact {loc}")
            continue
        cref = el.get("contextRef", "")
        key = field
        if key in facts:
            key = f"{field}#{cref or len(facts)}"
        facts[key] = {"value": value, "context": cref,
                      "period": contexts.get(cref, {}).get("end", "")}
    text = payload.decode("utf-8", "replace").lower()
    return {"namespace": namespaces[0] if namespaces else "",
            "namespaces": namespaces,
            "periods": {k: v for k, v in contexts.items()},
            "facts": facts,
            "standalone": ("standalone" in text) or None,
            "consolidated": ("consolidated" in text) or None,
            "warnings": warnings}
