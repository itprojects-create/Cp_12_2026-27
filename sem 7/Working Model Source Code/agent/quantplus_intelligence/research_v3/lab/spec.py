"""W2 typed StrategySpec + result contracts (blueprint §7.1, capital-sterile).

The spec is DATA, never code: a validated frozen record whose only behavioural
fields come from an allowlist (signal family, lookbacks, top-k, rebalance,
execution references). Free-text fields may not contain trade directives.
Every spec carries a deterministic fingerprint (sha256 of its canonical JSON)
and a preregistration timestamp; a spec is immutable once registered.

Negative controls (intentional future-leak, shuffled noise) are first-class
families but MUST be declared ``declared_negative_control=True`` — the runner
refuses leak-family specs without that flag, so a leak can never masquerade
as a real strategy; the challenger still catches and FAILs the control.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

# Capital-directive rejection (same philosophy as runtime app/research/schema.py:
# research prose passes, trade/position/leverage directives fail at parse time)
_FORBIDDEN = (
    re.compile(r"\b(buy|sell|short|cover)\s+[A-Z][A-Z0-9.\-]*\b"),
    re.compile(r"\b(place|executing?|route|send)\s+(a|an|the)?\s*(market|limit|stop)?\s*orders?\b",
               re.IGNORECASE),
    re.compile(r"\b(portfolio\s+)?weights?\s*[:=]\s*[\d\[]", re.IGNORECASE),
    re.compile(r"\b(leverage|notional)\s*[:=]\s*\d", re.IGNORECASE),
    re.compile(r"\b(target\s+price|take-?profit|stop-?loss)\b", re.IGNORECASE),
)

SIGNAL_FAMILIES = (
    "cross_sectional_momentum",   # 6/12m lookbacks; sector-relative variant needs verified sector map
    "near_52w_high",              # distance to 252-session available high
    "leak_control",               # NEGATIVE: uses decision-session close (unavailable)
    "noise_control",              # NEGATIVE: seeded random portfolio, no signal
)
MEMBERSHIP_MODES = ("disclosed", "strict")
REBALANCES = ("monthly", "quarterly")
EXIT_REFS = ("OPEN",)             # W1 boundary fix: execution-to-execution only
HORIZON_POLICY = ("next_rebalance_open",)
RESULT_STATES = ("DATA_BLOCKED", "RESEARCH", "REJECTED", "TRADE_OFF",
                 "OOS_VALIDATED", "SHADOW_CANDIDATE", "FUNCTIONAL_DEMO")
CHECK_STATUSES = ("PASS", "FAIL", "INCONCLUSIVE")


class SpecError(ValueError):
    """Typed spec validation failure (never a silent clamp)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _sterile_text(text: str, field_name: str) -> str:
    for rx in _FORBIDDEN:
        if rx.search(text or ""):
            raise SpecError(f"{field_name} contains a capital/execution directive")
    return text


@dataclass(frozen=True)
class UniverseSpec:
    universe_id: str = "nifty50"
    membership_mode: str = "disclosed"       # disclosed (weak rows carried) | strict
    require_entry_session_bar: bool = True   # fill only names that trade on the entry session
    max_names: int = 50

    def __post_init__(self):
        if self.membership_mode not in MEMBERSHIP_MODES:
            raise SpecError(f"membership_mode {self.membership_mode!r} not allowed")


@dataclass(frozen=True)
class SignalSpec:
    family: str
    lookback_sessions: int = 126       # 6m default; sweep may change within bounds
    skip_sessions: int = 0             # skip most-recent month option
    top_k: int = 10
    min_history_sessions: int = 0      # extra warmup beyond lookback
    high_window_sessions: int = 252    # near_52w_high only; never a 65-bar proxy

    def __post_init__(self):
        if self.family not in SIGNAL_FAMILIES:
            raise SpecError(f"signal family {self.family!r} not in allowlist")
        if not (5 <= self.lookback_sessions <= 504):
            raise SpecError("lookback_sessions must be within [5, 504]")
        if not (0 <= self.skip_sessions <= self.lookback_sessions):
            raise SpecError("skip_sessions out of range")
        if not (1 <= self.top_k <= 50):
            raise SpecError("top_k must be within [1, 50]")
        if self.family == "near_52w_high" and self.high_window_sessions < 126:
            raise SpecError("52w-high window must cover >=126 sessions (no 65-bar proxy)")


@dataclass(frozen=True)
class ExecutionSpec:
    entry_ref: str = "OPEN"            # next eligible session open after decision
    exit_ref: str = "OPEN"             # W1 boundary fix: next rebalance's open
    rebalance: str = "monthly"
    capital_paise: int = 10_000_000    # Rs 1,00,000 total; per-name = capital/top_k
    slippage_bps: int = 0              # adverse execution-price adjustment scenario
    broker: str = "book_zero_brokerage"

    def __post_init__(self):
        if self.entry_ref != "OPEN" or self.exit_ref not in EXIT_REFS:
            raise SpecError("entry/exit refs must be executable OPEN (W1 boundary rule)")
        if self.rebalance not in REBALANCES:
            raise SpecError(f"rebalance {self.rebalance!r} not allowed")
        if self.capital_paise <= 0:
            raise SpecError("capital must be positive paise")
        if not (0 <= self.slippage_bps <= 200):
            raise SpecError("slippage_bps within [0, 200]")


@dataclass(frozen=True)
class WindowSpec:
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    holdout_start: str
    holdout_end: str
    embargo_sessions: int = 21         # >= max label horizon overlap between folds

    def __post_init__(self):
        a, b, c, d, e, f = (self.train_start, self.train_end, self.validation_start,
                            self.validation_end, self.holdout_start, self.holdout_end)
        for x in (a, b, c, d, e, f):
            if len(x) != 10:
                raise SpecError("window dates must be ISO YYYY-MM-DD")
        if not (a < b < c < d < e < f):
            raise SpecError("windows must be strictly chronological train<validation<holdout")
        if self.embargo_sessions < 0:
            raise SpecError("embargo must be non-negative")

    def phase_bounds(self, phase: str) -> tuple[str, str]:
        return {"train": (self.train_start, self.train_end),
                "validation": (self.validation_start, self.validation_end),
                "holdout": (self.holdout_start, self.holdout_end),
                "train_validation": (self.train_start, self.validation_end)}[phase]


@dataclass(frozen=True)
class StrategySpec:
    spec_id: str
    version: int
    hypothesis: str
    family: str = "other"
    universe: UniverseSpec = field(default_factory=UniverseSpec)
    signal: SignalSpec = field(default_factory=lambda: SignalSpec("cross_sectional_momentum"))
    execution: ExecutionSpec = field(default_factory=ExecutionSpec)
    windows: WindowSpec = field(default_factory=lambda: WindowSpec(
        "2015-06-01", "2021-12-31", "2022-01-01", "2023-12-31",
        "2024-06-21", "2026-09-17"))
    declared_negative_control: bool = False
    seed: int = 20261112
    created_at: str = field(default_factory=_utc_now_iso)
    notes: str = ""

    def __post_init__(self):
        if not self.spec_id or not re.fullmatch(r"[A-Za-z0-9_\-\.]+", self.spec_id):
            raise SpecError("spec_id required (letters/digits/_-. only)")
        if not isinstance(self.version, int) or self.version < 1:
            raise SpecError("version must be a positive integer")
        _sterile_text(self.hypothesis, "hypothesis")
        _sterile_text(self.notes, "notes")
        if self.signal.family in ("leak_control", "noise_control") \
                and not self.declared_negative_control:
            raise SpecError("negative-control families must declare "
                            "declared_negative_control=True")

    # --- identity ------------------------------------------------------------
    def core(self) -> dict:
        """Spec content without registration timestamps (the pinned rule set)."""
        d = asdict(self)
        d.pop("created_at", None)
        return d

    def fingerprint(self) -> str:
        return fingerprint(self.core())

    def preregistration_hash(self) -> str:
        """Fingerprint + creation instant: the preregistration contract."""
        return fingerprint({"spec": self.core(), "created_at": self.created_at})

    # --- phase access ----------------------------------------------------------
    def evaluate_phase(self) -> str:
        """Phases the runner may evaluate: everything except the sealed holdout,
        unless explicitly requested through evaluate_holdout()."""
        return "train_validation"

    def to_payload(self) -> dict:
        return asdict(self)


# --- result contracts (immutable, hash-addressed) ------------------------------

@dataclass(frozen=True)
class BacktestResult:
    """Immutable backtest output. ``result_id`` = sha256 of the canonical
    payload minus the id itself, the result's generated_at, and the embedded
    spec's registration-instant fields (created_at/preregistration_hash) —
    re-registering the same rule set and rerunning yields the same id."""

    spec: dict                 # full StrategySpec payload (includes prereg hash)
    spec_fingerprint: str
    result_id: str
    phase: str                 # train_validation | holdout
    status: str                # RESULT_STATES entry (runner-derived)
    months: tuple              # per-rebalance rows (dicts; see runner)
    fills: tuple               # per-name fill records incl. charges in paise
    abstained_months: tuple    # typed abstentions (never filled)
    labeled_segments: tuple    # contiguous labeled spans [(start_month, end_month, n)]
    continuous_chain_blocked: str | None   # None when whole-window NAV is sound
    nav: dict                  # net/gross/segments; whole-window NAV only when unbroken
    returns: dict              # absolute + benchmark-relative (separate fields)
    benchmark: dict            # provenance + basis labels
    price_basis: dict          # raw/adjusted labels + action-discontinuity counts
    costs: dict                # paise totals by category + slippage scenario
    scenario_nets: dict        # base vs double-cost net summaries
    warnings: tuple
    generated_at: str
    source_hashes: dict

    def __post_init__(self):
        if self.status not in RESULT_STATES:
            raise SpecError(f"result status {self.status!r} not allowed")

    def to_payload(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_payload(p: dict) -> "BacktestResult":
        return BacktestResult(**{k: (tuple(v) if isinstance(v, list) else v)
                                 for k, v in p.items()})


@dataclass(frozen=True)
class SweepResult:
    base_spec: dict
    grid: dict
    variants: tuple            # every tried configuration (incl. failures)
    n_trials: int
    n_failed: int
    surface_note: str          # plateau vs isolated-peak explanation (filled by analysis)
    plateau: dict | None       # best cell vs neighbour median (stability surface)
    best_variant: str | None
    best_neighbour_median: float | None
    used_holdout: bool         # MUST be False: sweeps never touch the holdout
    generated_at: str

    def __post_init__(self):
        if self.used_holdout:
            raise SpecError("sweep results may never include the sealed holdout")

    def to_payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ChallengeReport:
    run_id: str
    run_fingerprint: str
    checks: tuple              # [{check, status, reason, evidence}]
    n_pass: int
    n_fail: int
    n_inconclusive: int
    verdict: str               # RESULT_STATES entry
    verdict_reason: str
    generated_at: str

    def to_payload(self) -> dict:
        return asdict(self)
