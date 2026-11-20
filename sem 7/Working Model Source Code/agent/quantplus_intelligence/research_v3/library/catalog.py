"""The initial Wave 5 strategy-hypothesis catalog.

Source URLs identify rationale/methodology.  They are not redistribution rights
and do not establish that any hypothesis works in India.
"""
from __future__ import annotations

from .contracts import (
    Citation,
    StrategyRequirement,
    StrategyRevision,
    StrategyTemplate,
    StudyAttachment,
)


ACCESSED = "2026-11-14"
WINDOWS = {
    "train_start": "2015-06-01",
    "train_end": "2021-12-31",
    "validation_start": "2022-01-01",
    "validation_end": "2023-12-31",
    "holdout_start": "2024-06-21",
    "holdout_end": "2026-09-17",
    "embargo_sessions": 21,
}
UNIVERSE = {
    "universe_id": "nifty50",
    "membership_mode": "disclosed",
    "require_entry_session_bar": True,
    "max_names": 50,
}
EXECUTION = {
    "entry_ref": "OPEN",
    "exit_ref": "OPEN",
    "rebalance": "monthly",
    "capital_paise": 10_000_000,
    "slippage_bps": 10,
    "broker": "book_zero_brokerage",
}


def _common_requirements() -> tuple[StrategyRequirement, ...]:
    return (
        StrategyRequirement(
            "official_price_bars", "market_data",
            "Source-labelled official daily observations available at the decision clock",
            ("diagnostic",), "VERIFIED_RETROSPECTIVE", None,
            "W1 official bhavcopy archive; retrospective local capture",
        ),
        StrategyRequirement(
            "pit_membership", "universe",
            "As-of membership with row-level historical knowability",
            ("economics", "forward"), "PARTIAL", "DATA_BLOCKED_MEMBERSHIP_QUALITY",
            "W1 has mixed strict and snapshot_floor spells",
        ),
        StrategyRequirement(
            "corporate_actions", "return_basis",
            "Verified split/bonus/dividend coverage for every holding window",
            ("economics", "forward"), "MISSING", "DATA_BLOCKED_CORPORATE_ACTIONS",
            "W1 action coverage is unresolved; raw price observations are not total returns",
        ),
        StrategyRequirement(
            "historical_fee_schedule", "costs",
            "Date-valid fee schedule across the complete evaluation window",
            ("economics", "forward"), "PARTIAL", "DATA_BLOCKED_FEE_HISTORY",
            "Exact tested schedule begins 2026-03-01 only",
        ),
        StrategyRequirement(
            "untouched_holdout", "evaluation",
            "Never-revealed temporal holdout independent of W2/W3 development",
            ("forward",), "REVEALED_NOT_FRESH", "W2_HOLDOUT_REUSE_REFUSED",
            "W2 holdout 2024-06-21..2026-09-17 was revealed and remains burned",
        ),
        StrategyRequirement(
            "operator_approval", "governance",
            "Explicit paper-only forward-study approval after preregistration",
            ("forward",), "MISSING", "FORWARD_APPROVAL_REQUIRED",
            "No W5 strategy has operator promotion approval",
        ),
    )


def _attachment(spec_id: str, result_id: str, spec_fingerprint: str,
                conclusion: str) -> StudyAttachment:
    return StudyAttachment(
        study_id=f"wave2:{spec_id}",
        immutable_result_ref=result_id,
        result_sha256=result_id,
        evaluation_cutoff="2023-12-31",
        conclusion=conclusion,
        maturity_label="HISTORICAL_RETROSPECTIVE_ECONOMICS_DATA_BLOCKED",
        source_hashes=(("wave2_strategy_spec_fingerprint", spec_fingerprint),),
        limitations=(
            "W2 holdout was subsequently revealed and cannot be reused as untouched",
            "raw price fills versus TRI are basis-incompatible without action coverage",
        ),
    )


def _near_high() -> StrategyRevision:
    citation = Citation(
        "george-hwang-2004",
        "The 52-Week High and Momentum Investing",
        "Thomas J. George and Chuan-Yang Hwang",
        "https://doi.org/10.1111/j.1540-6261.2004.00695.x",
        ACCESSED,
        "peer_reviewed_article_reference",
        "Bibliographic link only; article text is not redistributed.",
        "DOI_CITATION_RESOLVED_2026-11-14",
    )
    template = StrategyTemplate(
        strategy_id="near-52w-high-price-momentum",
        title="Near-52-week-high price momentum",
        author_source="George and Hwang (2004) hypothesis; independently test on NSE",
        citations=(citation,), source_accessed_date=ACCESSED,
        description=("Ranks as-of members by proximity to the highest available close over "
                     "252 observed sessions; broad windows/top-k and adverse cost scenarios "
                     "must be logged."),
        falsifiable_thesis=("Among as-of NIFTY 50 members, names nearer their prior 252-session "
                            "high have stronger subsequent price-only returns than matched "
                            "placebos after turnover controls."),
        decision_clock="Monthly decision after prior daily bars become available; next session OPEN",
        instrument_universe="As-of NIFTY 50 membership; weak membership rows disclosed",
        pit_requirements=("252 available sessions", "as-of membership", "next-open fills"),
        quote_return_basis="Raw official close signal; next-open price-only fills",
        corporate_action_requirements="Verified actions required for economic/total-return claims",
        required_fundamental_availability="Not applicable",
        fee_validity_span="Exact fee economics only from 2026-03-01; earlier periods blocked",
        known_flaws=("52-week anchor may proxy ordinary momentum", "high turnover and crowding",
                     "raw prices are action-sensitive"),
        anti_hypotheses=("effect vanishes under broad parameters", "costs dominate",
                         "matched random portfolios perform as well"),
        valid_horizons=("1_month", "3_months", "6_months"),
        evaluation_protocol=("Bounded sweep: high_window 189/252/315, top_k 5/10/15, "
                             "slippage/cost stress, placebo and date-block uncertainty; no W2 "
                             "holdout reuse for promotion."),
        source_licensing_provenance="Citation metadata only; W1 market-data rights apply separately",
    )
    return StrategyRevision(
        template=template,
        semantic_version="1.0.0",
        normalized_strategy_spec={
            "dsl_version": "research_v3.lab.StrategySpec/1",
            "compiler_supported": True,
            "signal": {"family": "near_52w_high", "lookback_sessions": 126,
                       "skip_sessions": 0, "top_k": 10, "min_history_sessions": 0,
                       "high_window_sessions": 252},
            "parameter_grid": {"high_window_sessions": [189, 252, 315],
                               "top_k": [5, 10, 15], "slippage_bps": [10, 25, 50]},
            "universe": UNIVERSE, "execution": EXECUTION, "windows": WINDOWS,
        },
        requirements=_common_requirements(),
        lifecycle_state="RESEARCH_DIAGNOSTIC",
        study_attachments=(_attachment(
            "wave2.h2.near-52w-high",
            "3cd201d69fd93333e1e9ce3e516dca6ab93fed61d6217abe087444dd916768e8",
            "d1318f6e3f605e4b995e1b448b2d36b35b137f46ffd97a1e23d95b9cde560906",
            "W2 historical diagnostic did not establish net economic edge; DATA_BLOCKED",
        ),),
        revision_note="Preserves the W2 rule; library metadata and broad future protocol added.",
    )


def _momentum() -> StrategyRevision:
    citation = Citation(
        "nse-nifty200-momentum30-methodology",
        "Nifty200 Momentum 30 Index methodology/background",
        "NSE Indices Limited",
        "https://niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30-index-static",
        ACCESSED,
        "official_index_methodology_entry_point",
        "Entry point is a methodology reference, not permission to redistribute index data.",
        "BLUEPRINT_CITED_ENTRY_POINT_NETWORK_UNAVAILABLE",
    )
    template = StrategyTemplate(
        strategy_id="nse-inspired-6-12m-price-momentum",
        title="NSE-methodology-inspired 6/12-month price momentum",
        author_source="NSE Indices methodology inspiration; not official index replication",
        citations=(citation,), source_accessed_date=ACCESSED,
        description=("Tests separate 126- and 252-session price-momentum variants with "
                     "volatility reported as a diagnostic; it does not claim to reproduce "
                     "Nifty200 Momentum 30 constituents or weights."),
        falsifiable_thesis=("Broad 6- and 12-month as-of price-momentum ranks provide stable "
                            "forward cross-sectional diagnostics beyond matched equal-weight and "
                            "random controls in the local NSE panel."),
        decision_clock="Monthly after daily-bar availability; next observed session OPEN",
        instrument_universe="As-of NIFTY 50 research universe, not Nifty 200 replication",
        pit_requirements=("126/252 available sessions", "as-of membership", "volatility history"),
        quote_return_basis="Raw official price momentum and next-open price-only fills",
        corporate_action_requirements="Complete verified actions required for economic use",
        required_fundamental_availability="Not applicable",
        fee_validity_span="Exact local fee schedule valid from 2026-03-01 only",
        known_flaws=("universe differs from official index", "single-leg variants are not the "
                     "official composite score", "turnover/crowding", "action-sensitive raw prices"),
        anti_hypotheses=("6m and 12m signs are unstable", "effect is crash/rebound selection",
                         "placebos dominate after multiplicity"),
        valid_horizons=("1_month", "3_months", "6_months"),
        evaluation_protocol=("Evaluate 126 and 252-session variants separately over a bounded "
                             "grid; report every trial, turnover/cost stress and dependence-aware "
                             "uncertainty. Never label as official index replication."),
        source_licensing_provenance="Official methodology entry point only; no index data redistributed",
    )
    return StrategyRevision(
        template=template,
        semantic_version="1.0.0",
        normalized_strategy_spec={
            "dsl_version": "research_v3.lab.StrategySpec/1",
            "compiler_supported": True,
            "signal": {"family": "cross_sectional_momentum", "lookback_sessions": 126,
                       "skip_sessions": 21, "top_k": 10, "min_history_sessions": 0,
                       "high_window_sessions": 252},
            "parameter_grid": {"lookback_sessions": [126, 252],
                               "skip_sessions": [0, 21], "top_k": [5, 10, 15]},
            "official_replication": False,
            "universe": UNIVERSE, "execution": EXECUTION, "windows": WINDOWS,
        },
        requirements=_common_requirements(),
        lifecycle_state="RESEARCH_DIAGNOSTIC",
        study_attachments=(_attachment(
            "wave2.h1.momentum-6m",
            "c8dd29d9cc33a8943bca597fb8da7d97f8832aa25da55ee91bc70919fc82b02e",
            "d11f28f26e25fe79d7e0e269337e79d288aeb6ea012091a6292ec07fc29eccde",
            "W2 6-month historical diagnostic found no confirmed gross or net edge",
        ),),
        revision_note="Separate variants only; no unsupported 6/12 composite compiler claim.",
    )


def _pead() -> StrategyRevision:
    citation = Citation(
        "bernard-thomas-1989",
        "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?",
        "Victor L. Bernard and Jacob K. Thomas",
        "https://doi.org/10.2307/2491062",
        ACCESSED,
        "peer_reviewed_article_reference",
        "Bibliographic link only; article text is not redistributed.",
        "DOI_CITATION_RESOLVED_2026-11-14",
    )
    template = StrategyTemplate(
        strategy_id="post-earnings-announcement-drift",
        title="Post-earnings-announcement drift (PEAD)",
        author_source="Bernard and Thomas (1989) hypothesis; India applicability untested",
        citations=(citation,), source_accessed_date=ACCESSED,
        description=("Tests delayed price response after a contemporaneously available, "
                     "material earnings surprise. W5 has neither an eligible historical event "
                     "corpus nor a compatible W2 event-signal compiler."),
        falsifiable_thesis=("Large signed earnings surprises known before the decision cutoff are "
                            "followed by same-direction abnormal returns over preregistered "
                            "horizons after costs and event-time controls."),
        decision_clock="First eligible session after official result and surprise inputs are available",
        instrument_universe="As-of eligible NSE issuers with resolved ISIN and contemporaneous results",
        pit_requirements=("official result timestamp", "as-filed estimates", "surprise materiality",
                          "blind forward labels"),
        quote_return_basis="Next eligible observed quote; benchmark-consistent total-return basis",
        corporate_action_requirements="Complete action coverage across every event window",
        required_fundamental_availability="As-filed results and pre-announcement consensus, both PIT",
        fee_validity_span="Date-valid charges for each event window",
        known_flaws=("estimate revisions", "announcement-time ambiguity", "event clustering",
                     "selection and survivorship bias"),
        anti_hypotheses=("surprise is not knowable at cutoff", "drift disappears after costs",
                         "effect is sector/market beta"),
        valid_horizons=("1_session", "5_sessions", "20_sessions", "60_sessions"),
        evaluation_protocol=("Forward-only capture and blind double-review gold labels; preregister "
                             "event rule and paired controls before outcome reveal."),
        source_licensing_provenance="Citation metadata only; issuer-event and estimate rights independent",
    )
    requirements = _common_requirements() + (
        StrategyRequirement(
            "contemporaneous_event_corpus", "events",
            "Official results captured contemporaneously with immutable first-seen timestamps",
            ("diagnostic", "economics", "forward"), "MISSING",
            "DATA_BLOCKED_EVENT_CORPUS",
            "W4 has synthetic authored rows only; no real contemporaneous corpus",
        ),
        StrategyRequirement(
            "event_signal_compiler", "dsl",
            "Typed event surprise/materiality clause supported by the research compiler",
            ("diagnostic", "economics", "forward"), "MISSING",
            "NOT_IMPLEMENTED_SPEC_CONTRACT",
            "Frozen W2 StrategySpec has no event condition; no clause is silently dropped",
        ),
    )
    return StrategyRevision(
        template=template,
        semantic_version="1.0.0",
        normalized_strategy_spec={
            "dsl_version": "research_v3.library.EventStrategySpec/1-proposed",
            "compiler_supported": False,
            "signal": {"family": "post_earnings_drift", "surprise_field": "UNAVAILABLE",
                       "materiality_threshold": "PREREGISTER_BEFORE_CAPTURE"},
            "entry": "next_eligible_observed_quote",
            "outcome_horizons_sessions": [1, 5, 20, 60],
        },
        requirements=requirements,
        lifecycle_state="DATA_BLOCKED",
        revision_note="Typed blocked fixture: DATA_BLOCKED_EVENT_CORPUS + NOT_IMPLEMENTED_SPEC_CONTRACT.",
    )


def initial_strategy_revisions() -> tuple[StrategyRevision, ...]:
    """Stable order is part of the manifest contract."""
    return (_near_high(), _momentum(), _pead())
