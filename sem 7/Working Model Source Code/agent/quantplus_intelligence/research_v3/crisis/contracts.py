"""Typed contracts for descriptive historical stress replay.

The vocabulary intentionally has no forecast/probability/expected-return state.
Results describe observed historical price paths for supported mappings only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from quantplus_intelligence.research_v3.wave5_common import is_sha256, semantic_sha256


MAPPING_KINDS = ("SAME_INSTRUMENT", "SECTOR_PROXY", "INDEX_PROXY", "NO_HISTORICAL_MATCH")
PRIVACY_CLASSES = ("HYPOTHETICAL", "REDACTED")
OUTPUT_LABELS = ("HISTORICAL_RETROSPECTIVE",)


@dataclass(frozen=True)
class CrisisEvent:
    event_id: str
    name: str
    geography: str
    description: str
    source_title: str
    source_url_or_local_ref: str
    source_accessed_date: str
    source_verification_status: str
    event_start: str
    event_end: str
    date_basis: str
    supporting_sources: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class CrisisWindow:
    start_session: str
    end_session: str
    recovery_observation_end: str
    exchange_calendar: str

    def __post_init__(self):
        if not self.start_session <= self.end_session <= self.recovery_observation_end:
            raise ValueError("crisis sessions must be ordered start <= end <= observation end")


@dataclass(frozen=True)
class ExposurePosition:
    holding_id: str
    current_symbol: str
    current_isin: str | None
    weight: float
    sector: str | None

    def __post_init__(self):
        if not self.holding_id or not self.current_symbol:
            raise ValueError("holding_id and current_symbol are required")
        if not 0.0 < self.weight <= 1.0:
            raise ValueError("position weight must be within (0, 1]")


@dataclass(frozen=True)
class PortfolioExposureSnapshot:
    snapshot_id: str
    as_of: str
    privacy_class: str
    positions: tuple[ExposurePosition, ...]
    note: str

    def __post_init__(self):
        if self.privacy_class not in PRIVACY_CLASSES:
            raise ValueError("only HYPOTHETICAL or REDACTED portfolios are accepted")
        if not self.positions:
            raise ValueError("portfolio requires at least one position")
        if abs(sum(position.weight for position in self.positions) - 1.0) > 1e-9:
            raise ValueError("portfolio weights must sum to exactly 1")
        ids = [position.holding_id for position in self.positions]
        if len(ids) != len(set(ids)):
            raise ValueError("holding_id must be unique inside a snapshot")

    @property
    def semantic_hash(self) -> str:
        return semantic_sha256(asdict(self))


@dataclass(frozen=True)
class HistoricalProxyMapping:
    holding_id: str
    mapping_kind: str
    historical_symbol: str | None
    historical_isin: str | None
    reason: str
    source: str

    def __post_init__(self):
        if self.mapping_kind not in MAPPING_KINDS:
            raise ValueError(f"unknown mapping kind {self.mapping_kind!r}")
        if self.mapping_kind == "NO_HISTORICAL_MATCH":
            if self.historical_symbol is not None:
                raise ValueError("NO_HISTORICAL_MATCH cannot carry a fabricated symbol")
        elif not self.historical_symbol:
            raise ValueError("a mapped holding requires historical_symbol")


@dataclass(frozen=True)
class ReplayAssumptions:
    price_basis: str
    action_policy: str
    dividend_policy: str
    rebalance_policy: str
    missing_bar_policy: str
    unmatched_weight_policy: str
    benchmark: str
    benchmark_basis: str
    source_data_id: str
    source_data_sha256: str
    source_first_seen_at: str
    source_rights_label: str
    coverage_threshold: float = 0.95

    def __post_init__(self):
        if self.price_basis != "RAW_UNADJUSTED_CLOSE_PRICE_ONLY":
            raise ValueError("W5 replay supports only explicitly labelled raw price observations")
        if self.action_policy != "NO_ACTION_IMPUTATION":
            raise ValueError("corporate actions may not be invented or silently normalized")
        if self.missing_bar_policy != "EXCLUDE_SESSION_NO_FORWARD_FILL":
            raise ValueError("missing bars must fail closed without forward fill")
        if self.unmatched_weight_policy != "REPORT_UNMATCHED_DO_NOT_ASSUME_CASH":
            raise ValueError("unmatched weight may not be treated as flat cash by assumption")
        if not self.source_data_id or not is_sha256(self.source_data_sha256):
            raise ValueError("replay source identity and full sha256 are required")
        if not self.source_first_seen_at or not self.source_rights_label:
            raise ValueError("source first-seen and rights labels are required")
        if not 0.0 <= self.coverage_threshold <= 1.0:
            raise ValueError("coverage_threshold must be in [0,1]")


@dataclass(frozen=True)
class CrisisReplayResult:
    event: dict
    window: dict
    snapshot_hash: str
    mapping_hash: str
    assumptions: dict
    status: str
    output_label: str
    supported_weight: float
    unmatched_weight: float
    expected_sessions: int
    observed_common_sessions: int
    observed_session_coverage: float
    component_results: tuple[dict, ...]
    supported_components_return: float | None
    full_portfolio_return: None
    peak_to_trough_drawdown: float | None
    drawdown_peak_session: str | None
    drawdown_trough_session: str | None
    worst_observed_day: dict | None
    recovery: dict
    sector_contributions: tuple[dict, ...]
    benchmark: dict
    data_quality: str
    limitations: tuple[str, ...]
    prohibited_interpretations: tuple[str, ...]
    authority: str = "RESEARCH_ONLY"

    def __post_init__(self):
        if self.output_label not in OUTPUT_LABELS:
            raise ValueError("crisis replay must be labelled HISTORICAL_RETROSPECTIVE")
        if self.authority != "RESEARCH_ONLY":
            raise ValueError("crisis replay has no execution authority")
        if self.full_portfolio_return is not None:
            raise ValueError("full return is unavailable when unmatched weight is not assumed")

    def semantic_payload(self) -> dict:
        payload = asdict(self)
        payload.pop("authority", None)
        return payload

    @property
    def result_id(self) -> str:
        return semantic_sha256(self.semantic_payload())

    def to_payload(self) -> dict:
        payload = asdict(self)
        payload["result_id"] = self.result_id
        return payload
