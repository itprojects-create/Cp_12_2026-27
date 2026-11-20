"""Typed W3 contracts: FeatureSnapshot, ReturnLabel, TrainFold, ModelRun.

Conventions inherited from the W2 lab (`research_v3.lab.spec`):
- frozen dataclasses, payload = asdict, identity = canonical-JSON sha256
  (`lab.spec.fingerprint`), registration instants never enter the identity;
- every abstention is a typed value (None / named reason), never a guess.

Money stays integer paise. All real-history labels keep their W1 provenance
(OFFICIAL_EXCHANGE_RECORD, RETROSPECTIVE reconstruction note applies to any
simulated decision on pre-archive history).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from quantplus_intelligence.research_v3.lab.spec import fingerprint

DATA_RIGHTS_BHAVCOPY = "official NSE EOD records, personal-research use per MANIFEST.md"
SOURCE_CLASS = "OFFICIAL_EXCHANGE_RECORD"
RETROSPECTIVE = "RETROSPECTIVE"          # simulated decision on pre-archive history
VENDOR_RECONSTRUCTION = "VENDOR_RECONSTRUCTION"

# Typed label/feature provenance states (never a silent pass)
ADMISSIBLE = "ADMISSIBLE"
DATA_BLOCKED_ACTION = "DATA_BLOCKED_ACTION_WINDOW"
DATA_BLOCKED_UNVERIFIED_ACTIONS = "DATA_BLOCKED_UNVERIFIED_ACTIONS"
NO_LABEL = "NO_LABEL"
BLOCK_REASONS = (ADMISSIBLE, DATA_BLOCKED_ACTION, DATA_BLOCKED_UNVERIFIED_ACTIONS,
                 NO_LABEL)


@dataclass(frozen=True)
class FeatureSnapshot:
    """One instrument's feature vector at one decision cutoff.

    ``features`` maps preregistered feature names to floats; an abstaining
    feature is absent from the dict and named in ``abstained_features`` with a
    typed reason. ``missing`` is the explicit missingness mask. No value is
    ever imputed from a later date (rule: out-of-cutoff events are scrubbed at
    construction, verified by tests).
    """

    symbol: str                 # panel key (spell symbol, alias-resolved)
    canonical_name: str         # as-of display name from members_at
    decision_session: str       # exchange session whose close is visible
    decision_ts: str            # execution cutoff (next session T00:15 IST)
    available_at: str           # the visible bar's own available_at
    features: dict[str, float]  # only computed features; abstains are absent
    missing: tuple[str, ...]    # explicit missingness mask
    abstained_features: dict[str, str]  # name -> typed reason
    universe: str = "nifty50"
    source_id: str = "nse_eod_bhavcopy_2015_2026_full"
    source_class: str = SOURCE_CLASS
    rights_label: str = DATA_RIGHTS_BHAVCOPY
    reconstruction_label: str = RETROSPECTIVE
    snapshot_id: str = ""       # canonical hash (filled in __post_init__)

    def __post_init__(self):
        object.__setattr__(self, "snapshot_id",
                           fingerprint({"snapshot": self.core()}))

    def core(self) -> dict:
        d = asdict(self)
        d.pop("snapshot_id", None)
        return d

    def vector(self, names: list[str]) -> list[float]:
        """Ordered vector for model families that need complete rows.

        Raises ValueError when any requested feature is absent (abstain or
        missing) — complete-row models see exactly what exists; NaN-tolerant
        models receive None placeholders instead.
        """
        out = []
        for n in names:
            v = self.features.get(n)
            if v is None:
                raise ValueError(f"feature {n} absent in {self.symbol}@{self.decision_session}")
            out.append(v)
        return out

    def vector_nan(self, names: list[str]) -> list[float | None]:
        return [self.features.get(n) for n in names]


@dataclass(frozen=True)
class ReturnLabel:
    """One (symbol, decision, horizon) executable label from the W1 engine.

    Built by ``research_v3.labels.executable_label`` — the single return
    truth. ``admissibility`` gates cross-sectional statistics: a label whose
    entry->exit window contains an unverified corporate-action-shaped
    discontinuity is DATA_BLOCKED (never a plausible number). Gross metrics
    may still include contaminated windows when explicitly disclosed
    (contamination stays in returns; no upward bias), mirroring W2.
    """

    symbol: str
    decision_ts: str
    decision_session: str                 # decision_baseline_session (W1 engine)
    horizon_sessions: int
    admissibility: str                 # BLOCK_REASONS entry
    status: str                        # OK / NO_FILL / NO_DECISION_BASELINE
    entry_session: str | None
    exit_session: str | None           # = label end (purge boundary)
    exit_extended: bool
    gross_return: float | None         # v3_gross_absolute (raw unadjusted fills)
    net_absolute_paise: int | None     # v3_trade_cash_pnl_paise; None when the
                                       # fee schedule does not cover the dates
    charges_status: str                # OK / SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE
    benchmark_relative: str            # typed: DATA_BLOCKED_BASIS_MISMATCH on
                                       # raw fills vs TRI (dividend-inclusive)
    benchmark_relative_raw: float | None  # diagnostic number on the RAW basis,
                                          # disclosed with the basis caveat only
    contamination: tuple[dict, ...]    # disclosed discontinuities inside window
    membership_strict: bool            # spell provenance of the universe row
    source_id: str = "nse_eod_bhavcopy_2015_2026_full"

    @property
    def usable_for_ic(self) -> bool:
        return (self.admissibility == ADMISSIBLE and self.status == "OK"
                and self.gross_return is not None)


@dataclass(frozen=True)
class TrainFold:
    """One purged walk-forward fold (session-ordered, never row-random)."""

    fold_id: str
    train_sessions: tuple[str, str]    # inclusive decision-session span
    val_sessions: tuple[str, str]
    embargo_sessions: int
    purge_rule: str = "drop train rows whose label exit_session >= "
    "val_start_minus_embargo"
    fold_id_hash: str = ""             # canonical hash (filled in __post_init__)

    def __post_init__(self):
        object.__setattr__(self, "fold_id_hash",
                           fingerprint({"fold": asdict(self)}))


@dataclass(frozen=True)
class ModelRun:
    """One fitted model's walk-forward output. ``run_id`` = canonical hash of
    semantic inputs (model family/config, horizon, fold, feature/label
    hashes) — never a timestamp; a complete rerun reproduces it exactly, and
    h5/h20/h60 runs of the same family+fold never collide."""

    run_id: str
    family: str
    config: dict
    horizon_sessions: int
    fold: TrainFold
    feature_names: tuple[str, ...]
    feature_hash: str
    label_hash: str
    n_train_rows: int
    n_train_days: int
    n_val_rows: int
    n_val_days: int
    n_excluded_rows: int               # abstain/missing exclusions (disclosed)
    predictions: tuple[dict, ...]      # {symbol, session, pred, ok}
    abstentions: tuple[dict, ...]      # {symbol, session, reason}
    diagnostics: dict                  # fold-level metrics (train + val)
    warnings: tuple[str, ...]
    authority: str = "RESEARCH_ONLY"   # never order authority

    @staticmethod
    def compute_run_id(family: str, config: dict, fold: TrainFold,
                       feature_hash: str, label_hash: str,
                       horizon_sessions: int) -> str:
        return fingerprint({"family": family, "config": config,
                            "horizon": horizon_sessions,
                            "fold": fold.fold_id_hash,
                            "features": feature_hash, "labels": label_hash})
