"""Frozen Pydantic v2 contracts (Build Plan Sec 4). Do not change field names without bumping /api/v1."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field

class Signal(BaseModel):
    model_config = {"frozen": True}
    name: str
    value: float
    direction: str = Field(pattern="^(bullish|bearish|neutral)$")

class Evidence(BaseModel):
    model_config = {"frozen": True}
    source: str
    ref: str
    available_at: datetime

class AnalystReport(BaseModel):
    model_config = {"frozen": True}
    agent: str
    summary: str = Field(min_length=10, max_length=2000)
    signals: list[Signal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)

class DebateTurn(BaseModel):
    model_config = {"frozen": True}
    stance: str = Field(pattern="^(long|short)$")
    argument: str = Field(min_length=10, max_length=2000)
    rebuttal_to: str = Field(default="")
    confidence_delta: float = Field(ge=-1.0, le=1.0)

class MechanismType(str, Enum):
    MOMENTUM_CONTINUATION = "MOMENTUM_CONTINUATION"
    MEAN_REVERSION = "MEAN_REVERSION"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    OTHER = "OTHER"

class Thesis(BaseModel):
    model_config = {"frozen": True}
    direction: str = Field(pattern="^(long|short|flat)$")
    conviction: float = Field(ge=0.0, le=1.0)
    key_evidence: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    # Structural mechanism classification (M3 gate input). Default OTHER (not
    # Pydantic-required) for checkpoint/probe backward-compat with pre-M3
    # payloads — same precedent as Challenge.raw_override_applied. The Research
    # Manager prompt mandates setting it explicitly, so fresh theses always
    # carry a real classification; the M3 gate only fires on an explicit
    # MOMENTUM_CONTINUATION (unknown/other is never gated).
    mechanism_type: MechanismType = MechanismType.OTHER

class ThesisStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WEAKENED = "WEAKENED"
    BROKEN = "BROKEN"

class Challenge(BaseModel):
    model_config = {"frozen": True}
    status: ThesisStatus
    core_claim_restated: str = Field(min_length=10, max_length=500)
    new_evidence_considered: list[str] = Field(default_factory=list)
    duplicate_risks_discarded: list[str] = Field(default_factory=list)
    direction_symmetry_check_passed: bool
    raw_override_applied: bool = False
    reasons: list[str] = Field(default_factory=list)

class RawExhaustionSignals(BaseModel):
    """Typed Devil input (Part A): raw numeric exhaustion facts, NOT analyst narrative.

    Sourced from the same exhaustion_features() dict computed for the Technical
    Analyst and passed through session checkpoints — never recomputed downstream,
    so the Devil evaluates exactly what the Technical saw.
    """
    model_config = {"frozen": True}
    flush_flag: bool
    blowoff_flag: bool
    ret_5d_pct: float
    dist_from_20d_low_pct: float
    dist_from_20d_high_pct: float

class TradeProposal(BaseModel):
    model_config = {"frozen": True}
    instrument: str
    direction: str = Field(pattern="^(long|short|flat)$")
    size_pct: float = Field(ge=0.0, le=1.0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)

class RiskVerdict(BaseModel):
    model_config = {"frozen": True}
    approve: bool
    adjusted_size: float = Field(ge=0.0, le=1.0)
    notes: str = Field(default="", max_length=2000)

class FinalDecision(BaseModel):
    model_config = {"frozen": True}
    action: str = Field(pattern="^(buy|sell|hold)$")
    size: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=10, max_length=2000)
    thesis_version: int = Field(ge=1)
    # Governance migration §3: session-pipeline output is RESEARCH_ONLY by type.
    # These literals are the capital boundary — money-path code must reject any
    # decision object lacking them (see governance.constitution.assert_research_only).
    authority: str = Field(default="RESEARCH_ONLY", pattern="^RESEARCH_ONLY$")
    cannot_create_position: bool = True
    cannot_reverse_position: bool = True
    cannot_increase_exposure: bool = True

class SessionRequest(BaseModel):
    instrument: str = Field(examples=["RELIANCE.NS"])
    as_of: datetime
    interval: str = Field(default="1d", pattern="^(1d|60m|15m)$")
    force_rerun: bool = False
    # Day 2 additive-only (NEW_PLAN T2.1): optional broker-neutral book.
    # Absent => legacy behavior (no portfolio block, sid unchanged).
    # Frontend already built: must stay optional with default None.
    portfolio: dict | None = None
    # Day 4 sandbox (NEW_PLAN): manager retry mode, default frozen pipeline.
    manager_mode: str = Field(default="frozen", pattern="^(frozen|retry)$")

class SessionStatus(BaseModel):
    id: str
    status: str
    decision: FinalDecision | None = None

class StageEvent(BaseModel):
    stage: str
    agent: str
    status: str
    output_ref: str = ""

# --- Day 6 frontend surface (all additive; /api/v1 shapes unchanged) ---

class KillSwitchState(BaseModel):
    model_config = {"frozen": True}
    engaged: bool
    reason: str = ""
    updated_ts: str | None = None

class ControlRequest(BaseModel):
    model_config = {"frozen": True}
    engage: bool
    reason: str = ""

class ArenaVariant(BaseModel):
    model_config = {"frozen": True}
    id: str
    name: str
    status: str
    strikes: int
    probation: bool
    parent_id: str | None = None
    genome: dict

class ArenaEvent(BaseModel):
    model_config = {"frozen": True}
    seq: int
    ts: str
    variant_id: str
    event: str
    detail: str = ""

class ArenaState(BaseModel):
    model_config = {"frozen": True}
    living: list[ArenaVariant]
    seed_bank: list[dict]
    allocation: dict[str, float]
    cap: int
    as_of: str
