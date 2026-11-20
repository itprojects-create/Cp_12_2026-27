"""Immutable contracts for cited strategy hypotheses.

A library revision is a testable research hypothesis, not an endorsement.  It
cannot infer ``PROFITABLE`` (that state intentionally does not exist), mutate a
paper account, or promote a revealed W2 holdout into fresh evidence.
"""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from quantplus_intelligence.research_v3.wave5_common import semantic_sha256


LIFECYCLE_STATES = (
    "NOT_TESTED",
    "RUNNABLE_DIAGNOSTIC",
    "DATA_BLOCKED",
    "REJECTED",
    "RESEARCH_DIAGNOSTIC",
    "FORWARD_ELIGIBLE_PENDING_APPROVAL",
    "RETIRED",
)
REQUIREMENT_STATES = (
    "VERIFIED",
    "VERIFIED_RETROSPECTIVE",
    "PARTIAL",
    "MISSING",
    "UNVERIFIED",
    "REVEALED_NOT_FRESH",
    "NOT_APPLICABLE",
)
ELIGIBILITY_STATES = (
    "RUNNABLE_DIAGNOSTIC",
    "DATA_BLOCKED",
    "FORWARD_ELIGIBLE_PENDING_APPROVAL",
    "REJECTED",
)
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class Citation:
    citation_id: str
    title: str
    authors_or_issuer: str
    url_or_local_ref: str
    accessed_date: str
    source_type: str
    licensing_note: str
    verification_status: str

    def __post_init__(self):
        if not self.citation_id or not self.title or not self.url_or_local_ref:
            raise ValueError("citation id, title and URL/local reference are required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.accessed_date):
            raise ValueError("citation accessed_date must be YYYY-MM-DD")


@dataclass(frozen=True)
class StrategyRequirement:
    requirement_id: str
    category: str
    description: str
    mandatory_for: tuple[str, ...]
    observed_state: str
    refusal_code: str | None
    provenance: str

    def __post_init__(self):
        if self.observed_state not in REQUIREMENT_STATES:
            raise ValueError(f"unknown requirement state {self.observed_state!r}")
        allowed = {"diagnostic", "economics", "forward"}
        if not set(self.mandatory_for).issubset(allowed):
            raise ValueError("mandatory_for contains an unknown eligibility lane")
        if self.observed_state in {"MISSING", "UNVERIFIED", "PARTIAL", "REVEALED_NOT_FRESH"} \
                and not self.refusal_code:
            raise ValueError("non-verified mandatory evidence needs a typed refusal_code")


@dataclass(frozen=True)
class StudyAttachment:
    study_id: str
    immutable_result_ref: str
    result_sha256: str
    evaluation_cutoff: str
    conclusion: str
    maturity_label: str
    source_hashes: tuple[tuple[str, str], ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyTemplate:
    strategy_id: str
    title: str
    author_source: str
    citations: tuple[Citation, ...]
    source_accessed_date: str
    description: str
    falsifiable_thesis: str
    decision_clock: str
    instrument_universe: str
    pit_requirements: tuple[str, ...]
    quote_return_basis: str
    corporate_action_requirements: str
    required_fundamental_availability: str
    fee_validity_span: str
    known_flaws: tuple[str, ...]
    anti_hypotheses: tuple[str, ...]
    valid_horizons: tuple[str, ...]
    evaluation_protocol: str
    source_licensing_provenance: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]+", self.strategy_id):
            raise ValueError("strategy_id must be stable lowercase dotted/kebab identity")
        if not self.citations:
            raise ValueError("at least one source citation is required")
        if not self.falsifiable_thesis or not self.evaluation_protocol:
            raise ValueError("falsifiable thesis and evaluation protocol are required")


@dataclass(frozen=True)
class StrategyRevision:
    template: StrategyTemplate
    semantic_version: str
    normalized_strategy_spec: Mapping[str, Any]
    requirements: tuple[StrategyRequirement, ...]
    lifecycle_state: str
    study_attachments: tuple[StudyAttachment, ...] = ()
    revision_note: str = ""

    def __post_init__(self):
        if not SEMVER.fullmatch(self.semantic_version):
            raise ValueError("semantic_version must be MAJOR.MINOR.PATCH")
        if self.lifecycle_state not in LIFECYCLE_STATES:
            raise ValueError(f"unknown lifecycle state {self.lifecycle_state!r}")
        if not isinstance(self.normalized_strategy_spec, Mapping):
            raise ValueError("normalized_strategy_spec must be typed data, never code")
        if "dsl_version" not in self.normalized_strategy_spec:
            raise ValueError("normalized strategy spec must pin dsl_version")

    @property
    def strategy_id(self) -> str:
        return self.template.strategy_id

    @property
    def dsl_hash(self) -> str:
        return semantic_sha256(dict(self.normalized_strategy_spec))

    def semantic_payload(self) -> dict:
        return {
            "template": asdict(self.template),
            "semantic_version": self.semantic_version,
            "normalized_strategy_spec": copy.deepcopy(dict(self.normalized_strategy_spec)),
            "requirements": [asdict(item) for item in self.requirements],
            "lifecycle_state": self.lifecycle_state,
            "study_attachments": [asdict(item) for item in self.study_attachments],
            "revision_note": self.revision_note,
        }

    @property
    def semantic_hash(self) -> str:
        return semantic_sha256(self.semantic_payload())

    @property
    def revision_id(self) -> str:
        return f"{self.strategy_id}@{self.semantic_version}:{self.semantic_hash[:16]}"

    def to_payload(self) -> dict:
        payload = self.semantic_payload()
        payload.update(
            strategy_id=self.strategy_id,
            dsl_hash=self.dsl_hash,
            semantic_hash=self.semantic_hash,
            revision_id=self.revision_id,
        )
        return payload


@dataclass(frozen=True)
class EligibilityReport:
    revision_id: str
    requested_lane: str
    status: str
    executable_diagnostic: bool
    economics_eligible: bool
    forward_eligible: bool
    blockers: tuple[str, ...]
    requirement_states: tuple[tuple[str, str], ...]
    holdout_reuse_refused: bool
    authority: str = "RESEARCH_ONLY"

    def __post_init__(self):
        if self.status not in ELIGIBILITY_STATES:
            raise ValueError(f"unknown eligibility status {self.status!r}")
        if self.authority != "RESEARCH_ONLY":
            raise ValueError("strategy-library authority is permanently RESEARCH_ONLY")

    @property
    def report_id(self) -> str:
        return semantic_sha256(asdict(self))


def assess_eligibility(
    revision: StrategyRevision,
    requested_lane: str = "diagnostic",
    observed_overrides: Mapping[str, str] | None = None,
) -> EligibilityReport:
    """Fail-closed eligibility; never infers profitability or approval."""
    if requested_lane not in {"diagnostic", "economics", "forward"}:
        raise ValueError("requested_lane must be diagnostic, economics or forward")
    overrides = dict(observed_overrides or {})
    states = tuple(
        (req.requirement_id, overrides.get(req.requirement_id, req.observed_state))
        for req in revision.requirements
    )
    state_by_id = dict(states)
    blockers_by_lane: dict[str, list[str]] = {lane: [] for lane in ("diagnostic", "economics", "forward")}
    bad = {"MISSING", "UNVERIFIED", "PARTIAL", "REVEALED_NOT_FRESH"}
    for req in revision.requirements:
        state = state_by_id[req.requirement_id]
        if state not in REQUIREMENT_STATES:
            raise ValueError(f"override for {req.requirement_id} has invalid state {state!r}")
        if state in bad:
            for lane in req.mandatory_for:
                blockers_by_lane[lane].append(req.refusal_code or req.requirement_id)

    # Later lanes inherit earlier safety failures.
    diagnostic_blockers = blockers_by_lane["diagnostic"]
    economics_blockers = diagnostic_blockers + blockers_by_lane["economics"]
    forward_blockers = economics_blockers + blockers_by_lane["forward"]
    executable = not diagnostic_blockers
    economics = not economics_blockers
    forward = not forward_blockers
    holdout_refused = any(
        state == "REVEALED_NOT_FRESH" and rid == "untouched_holdout"
        for rid, state in states
    )

    requested_blockers = {
        "diagnostic": diagnostic_blockers,
        "economics": economics_blockers,
        "forward": forward_blockers,
    }[requested_lane]
    if revision.lifecycle_state == "REJECTED":
        status = "REJECTED"
    elif requested_lane == "forward" and forward:
        status = "FORWARD_ELIGIBLE_PENDING_APPROVAL"
    elif requested_lane == "diagnostic" and executable:
        status = "RUNNABLE_DIAGNOSTIC"
    elif requested_lane == "economics" and economics:
        status = "RUNNABLE_DIAGNOSTIC"
    else:
        status = "DATA_BLOCKED"
    return EligibilityReport(
        revision_id=revision.revision_id,
        requested_lane=requested_lane,
        status=status,
        executable_diagnostic=executable,
        economics_eligible=economics,
        forward_eligible=forward,
        blockers=tuple(dict.fromkeys(requested_blockers)),
        requirement_states=states,
        holdout_reuse_refused=holdout_refused,
    )


def compile_strategy_spec(
    revision: StrategyRevision,
    *,
    parameter_overrides: Mapping[str, int] | None = None,
):
    """Compile only the subset the frozen W2 DSL genuinely supports.

    Unsupported event conditions fail with ``NOT_IMPLEMENTED_SPEC_CONTRACT``;
    no incompatible clause is dropped to make a template appear runnable.
    """
    spec = dict(revision.normalized_strategy_spec)
    if not spec.get("compiler_supported", False):
        raise NotImplementedError("NOT_IMPLEMENTED_SPEC_CONTRACT")
    if spec.get("dsl_version") != "research_v3.lab.StrategySpec/1":
        raise NotImplementedError("NOT_IMPLEMENTED_SPEC_CONTRACT")
    signal_allowed = {"lookback_sessions", "skip_sessions", "top_k",
                      "high_window_sessions", "min_history_sessions"}
    execution_allowed = {"slippage_bps"}
    allowed = signal_allowed | execution_allowed
    overrides = dict(parameter_overrides or {})
    if not set(overrides).issubset(allowed):
        raise ValueError("parameter override is outside the frozen W2 allowlist")
    signal = dict(spec["signal"])
    signal.update({key: value for key, value in overrides.items()
                   if key in signal_allowed})
    execution = dict(spec["execution"])
    execution.update({key: value for key, value in overrides.items()
                      if key in execution_allowed})

    from quantplus_intelligence.research_v3.lab.spec import (
        ExecutionSpec,
        SignalSpec,
        StrategySpec,
        UniverseSpec,
        WindowSpec,
    )

    return StrategySpec(
        spec_id=f"library.{revision.strategy_id}.{revision.semantic_version}",
        version=int(revision.semantic_version.split(".")[0]) + 1,
        hypothesis=revision.template.falsifiable_thesis,
        family="library_hypothesis",
        universe=UniverseSpec(**spec["universe"]),
        signal=SignalSpec(**signal),
        execution=ExecutionSpec(**execution),
        windows=WindowSpec(**spec["windows"]),
        notes=("Compiled from W5 strategy-library revision " + revision.revision_id
               + "; no promotion or profitability implication."),
    )
