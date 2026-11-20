"""Goldset loader for the synthetic fixture set (W4.2).

The fixture is 100% synthetic (see the JSON header): invented issuers/tickers/
documents, authored labels, no real market data. The loader derives source and
excerpt hashes deterministically from the fixture text (so hash-forgery rows
can be exercised via an explicit override) and validates issuer/ticker
bindings against the fixture's alias registry. It never touches a network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from quantplus_intelligence.research_v3.events_ai.contracts import (
    IssuerAliasMap, IssuerEventEvidence, sha256_text)
from quantplus_intelligence.research_v3.events_ai.evaluate import GoldLabel

GOLDSET_VERSION = "events_ai_goldset/synthetic_v1"
_FIXTURE_PATH = Path(__file__).parent / "goldset" / "synthetic_v1.json"

EXPECTED_ADAPTERS = ("classify", "injection_review", "wrong_issuer_binding", "reject_evidence")


@dataclass(frozen=True)
class GoldsetRow:
    evidence: IssuerEventEvidence
    label: GoldLabel
    expected_adapter: str
    binding_problem: str | None


@dataclass(frozen=True)
class Goldset:
    version: str
    rows: tuple[GoldsetRow, ...]
    alias_map: IssuerAliasMap

    @property
    def evidence(self) -> list[IssuerEventEvidence]:
        return [row.evidence for row in self.rows]

    @property
    def labels(self) -> list[GoldLabel]:
        return [row.label for row in self.rows]


def load_goldset(path: Path | str | None = None) -> Goldset:
    fixture = json.loads((Path(path) if path else _FIXTURE_PATH).read_text(encoding="utf-8"))
    registry = fixture["issuer_registry"]
    alias_map = IssuerAliasMap(aliases={
        alias.upper(): info["ticker"]
        for issuer, info in registry.items()
        for alias in info["aliases"]
    })
    rows: list[GoldsetRow] = []
    for event in fixture["events"]:
        expected = event["expected_adapter"]
        if expected not in EXPECTED_ADAPTERS:
            raise ValueError(f"unknown expected_adapter: {expected}")
        ticker = event["ticker"]
        issuer_info = registry.get(event["canonical_issuer"])
        if issuer_info is None:
            raise ValueError(f"unknown issuer in fixture: {event['canonical_issuer']}")
        binding_problem = None if issuer_info["ticker"] == ticker.upper() else "WRONG_ISSUER_BINDING"
        source_sha = event.get("source_sha256_forced") or sha256_text(event["document_body"])
        aliases = tuple(sorted(alias.upper() for alias, canonical in alias_map.aliases.items()
                               if canonical == ticker.upper())) or (ticker.upper(),)
        evidence = IssuerEventEvidence(
            event_uid=event["event_uid"],
            canonical_issuer=event["canonical_issuer"],
            ticker=ticker,
            ticker_aliases=aliases,
            document_id=event["document_id"],
            source_uri=f"synthetic://official_announcements/{event['document_id']}",
            source_sha256=source_sha,
            excerpt_sha256=sha256_text(event["excerpt_text"]),
            excerpt_text=event["excerpt_text"],
            published_at=event["published_at"],
            first_seen_at=event["first_seen_at"],
            available_at=event["available_at"],
            decision_cutoff=event["decision_cutoff"],
            provider="synthetic_fixture",
            capture_method="authored_fixture",
            rights_label="test_fixture_only_no_real_market_data",
            source_integrity=event["source_integrity"],
            pit_class=event["pit_class"],
        )
        gold = event["gold"]
        label = GoldLabel(
            event_uid=event["event_uid"],
            event_type=gold["event_type"],
            guidance_change=gold["guidance_change"],
            materiality=gold["materiality"],
            needs_review=gold["needs_review"],
        )
        rows.append(GoldsetRow(evidence=evidence, label=label,
                               expected_adapter=expected, binding_problem=binding_problem))
    return Goldset(version=fixture["goldset_version"], rows=tuple(rows), alias_map=alias_map)
