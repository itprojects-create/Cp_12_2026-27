"""Deterministic Historical Crisis Replay over a read-only W1 warehouse."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict

from quantplus_intelligence.research_v3.wave5_common import semantic_sha256

from .contracts import (
    CrisisEvent,
    CrisisReplayResult,
    CrisisWindow,
    HistoricalProxyMapping,
    PortfolioExposureSnapshot,
    ReplayAssumptions,
)


def india_covid_2020_event() -> CrisisEvent:
    """Source-anchored event definition, separate from price measurements."""
    return CrisisEvent(
        event_id="india-covid-liquidity-selloff-2020",
        name="India COVID-19 liquidity selloff",
        geography="India / NSE",
        description=("Retrospective window from the pre-selloff NIFTY peak period to the "
                     "23 March 2020 trough session; descriptive historical stress only."),
        source_title="Reserve Bank of India, Financial Stability Report, July 2020",
        source_url_or_local_ref=(
            "https://www.rbi.org.in/Scripts/PublicationReportDetails.aspx?ID=1153"),
        source_accessed_date="2026-11-14",
        source_verification_status=(
            "OFFICIAL_RBI_REPORT_PAGE_RESOLVED_2026-11-14; "
            "DATES_INDEPENDENTLY_ALIGNED_TO_LOCAL_OFFICIAL_BARS"),
        event_start="2020-01-14",
        event_end="2020-03-23",
        date_basis=("RBI FSR anchors the COVID/panic-selloff context; the exact peak-to-trough "
                    "operational window is independently cross-checked against the cited market "
                    "chronology and both dates exist in local official exchange observations"),
        supporting_sources=(
            ("RBI FSR Chapter I: Macro-Financial Risks",
             "https://www.rbi.org.in/Scripts/PublicationReportDetails.aspx?UrlPage=&ID=1147",
             "official page resolved 2026-11-14; documents January panic sell-offs and March stress"),
            ("Major Nifty falls and recoveries (exact 14 Jan / 23 Mar chronology)",
             "https://www.moneycontrol.com/news/business/markets/major-nifty-falls-and-recoveries-in-2008-took-over-1000-days-for-recovery-5155021.html",
             "independent chronology located 2026-11-14; bibliographic use only"),
            ("NSE Historical Index Data entry point",
             "https://www.nseindia.com/reports-indices-historical-index-data",
             "official source entry; local W1 archive supplies observed boundary sessions"),
        ),
    )


def _expected_sessions(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT DISTINCT session FROM daily_bars WHERE session>=? AND session<=? "
        "ORDER BY session", (start, end))]


def _series(
    conn: sqlite3.Connection,
    symbol: str,
    start: str,
    end: str,
) -> tuple[list[tuple], set[str]]:
    rows = conn.execute(
        "SELECT session, close_paise, prev_close_paise, isin FROM daily_bars "
        "WHERE symbol=? AND series='EQ' AND session>=? AND session<=? ORDER BY session",
        (symbol.upper(), start, end),
    ).fetchall()
    isins = {row[3] for row in rows if row[3]}
    return rows, isins


def _drawdown(path: list[tuple[str, float]]) -> tuple[float, str, str]:
    peak_value = path[0][1]
    peak_session = path[0][0]
    worst = 0.0
    worst_peak = peak_session
    trough = peak_session
    for session, value in path:
        if value > peak_value:
            peak_value = value
            peak_session = session
        drawdown = value / peak_value - 1.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_session
            trough = session
    return worst, worst_peak, trough


def _worst_day(path: list[tuple[str, float]]) -> dict | None:
    if len(path) < 2:
        return None
    rows = [
        {"session": path[index][0], "return": path[index][1] / path[index - 1][1] - 1.0,
         "previous_observed_session": path[index - 1][0]}
        for index in range(1, len(path))
    ]
    return min(rows, key=lambda row: (row["return"], row["session"]))


def _benchmark(
    conn: sqlite3.Connection,
    assumptions: ReplayAssumptions,
    window: CrisisWindow,
) -> dict:
    rows = conn.execute(
        "SELECT session, tri_value FROM benchmark_bars WHERE index_code=? "
        "AND session>=? AND session<=? ORDER BY session",
        (assumptions.benchmark, window.start_session, window.recovery_observation_end),
    ).fetchall()
    by_date = dict(rows)
    if window.start_session not in by_date or window.end_session not in by_date:
        return {
            "index": assumptions.benchmark,
            "status": "UNAVAILABLE_BOUNDARY_SESSION",
            "return": None,
            "basis": assumptions.benchmark_basis,
            "comparability": "UNAVAILABLE",
        }
    return {
        "index": assumptions.benchmark,
        "status": "OBSERVED",
        "start_session": window.start_session,
        "end_session": window.end_session,
        "start_value": by_date[window.start_session],
        "end_value": by_date[window.end_session],
        "return": by_date[window.end_session] / by_date[window.start_session] - 1.0,
        "basis": assumptions.benchmark_basis,
        "comparability": "BASIS_MISMATCH_PRICE_ONLY_HOLDINGS_VS_TOTAL_RETURN_INDEX",
    }


def run_crisis_replay(
    conn: sqlite3.Connection,
    *,
    event: CrisisEvent,
    window: CrisisWindow,
    snapshot: PortfolioExposureSnapshot,
    mappings: tuple[HistoricalProxyMapping, ...],
    assumptions: ReplayAssumptions,
) -> CrisisReplayResult:
    """Replay observed raw prices without writes, imputation or hidden proxies."""
    conn.execute("PRAGMA query_only=ON")
    if event.event_start != window.start_session or event.event_end != window.end_session:
        raise ValueError("window boundaries must match the source-anchored crisis event")
    map_by_holding = {mapping.holding_id: mapping for mapping in mappings}
    if set(map_by_holding) != {position.holding_id for position in snapshot.positions}:
        raise ValueError("every position needs exactly one explicit mapping")
    if len(map_by_holding) != len(mappings):
        raise ValueError("duplicate mapping for a holding")

    expected_stress = _expected_sessions(conn, window.start_session, window.end_session)
    if not expected_stress or expected_stress[0] != window.start_session \
            or expected_stress[-1] != window.end_session:
        raise ValueError("event boundaries are not aligned to the observed exchange calendar")

    components: list[dict] = []
    supported: list[tuple[object, HistoricalProxyMapping, dict[str, int]]] = []
    unmatched_weight = 0.0
    limitations = [
        "RETROSPECTIVE reconstruction from an archive first captured after the event",
        "raw close prices only; dividends and unresolved split/bonus/demerger effects are not adjusted",
        "benchmark is TRI while holdings are price-only, so relative economics are not computed",
        "sector labels are user-supplied hypothetical snapshot metadata, not verified PIT sector membership",
    ]

    for position in snapshot.positions:
        mapping = map_by_holding[position.holding_id]
        if mapping.mapping_kind == "NO_HISTORICAL_MATCH":
            unmatched_weight += position.weight
            components.append({
                "holding_id": position.holding_id,
                "current_symbol": position.current_symbol,
                "weight": position.weight,
                "mapping_kind": mapping.mapping_kind,
                "historical_symbol": None,
                "status": "NO_HISTORICAL_MATCH",
                "reason": mapping.reason,
                "price_only_return": None,
            })
            continue

        rows, observed_isins = _series(
            conn, mapping.historical_symbol or "", window.start_session,
            window.recovery_observation_end)
        by_session = {session: close for session, close, _prev, _isin in rows}
        if mapping.historical_isin and mapping.historical_isin not in observed_isins:
            unmatched_weight += position.weight
            components.append({
                "holding_id": position.holding_id, "current_symbol": position.current_symbol,
                "weight": position.weight, "mapping_kind": mapping.mapping_kind,
                "historical_symbol": mapping.historical_symbol,
                "status": "IDENTITY_MISMATCH", "reason": "historical ISIN not observed",
                "price_only_return": None,
            })
            continue
        if mapping.mapping_kind == "SAME_INSTRUMENT" and position.current_isin \
                and position.current_isin not in observed_isins:
            unmatched_weight += position.weight
            components.append({
                "holding_id": position.holding_id, "current_symbol": position.current_symbol,
                "weight": position.weight, "mapping_kind": mapping.mapping_kind,
                "historical_symbol": mapping.historical_symbol,
                "status": "IDENTITY_MISMATCH", "reason": "current ISIN differs from historical bars",
                "price_only_return": None,
            })
            continue
        if window.start_session not in by_session or window.end_session not in by_session:
            unmatched_weight += position.weight
            components.append({
                "holding_id": position.holding_id, "current_symbol": position.current_symbol,
                "weight": position.weight, "mapping_kind": mapping.mapping_kind,
                "historical_symbol": mapping.historical_symbol,
                "status": "MISSING_BOUNDARY_BAR", "reason": "start or end close unavailable",
                "price_only_return": None,
            })
            continue

        # A raw >54% overnight discontinuity is action-shaped.  It is refused,
        # not normalized using an invented factor.
        discontinuities = []
        for session, close, previous, _isin in rows:
            if window.start_session <= session <= window.end_session and previous:
                ratio = close / previous
                if ratio < 0.65 or ratio > 1.54:
                    discontinuities.append({"session": session, "close_prev_ratio": ratio})
        if discontinuities:
            unmatched_weight += position.weight
            components.append({
                "holding_id": position.holding_id, "current_symbol": position.current_symbol,
                "weight": position.weight, "mapping_kind": mapping.mapping_kind,
                "historical_symbol": mapping.historical_symbol,
                "status": "AMBIGUOUS_ACTION_WINDOW", "reason": "action-shaped discontinuity",
                "discontinuities": discontinuities, "price_only_return": None,
            })
            continue

        price_return = by_session[window.end_session] / by_session[window.start_session] - 1.0
        row = {
            "holding_id": position.holding_id,
            "current_symbol": position.current_symbol,
            "current_isin": position.current_isin,
            "weight": position.weight,
            "sector": position.sector,
            "mapping_kind": mapping.mapping_kind,
            "historical_symbol": mapping.historical_symbol,
            "historical_isins_observed": sorted(observed_isins),
            "status": "OBSERVED_PRICE_ONLY",
            "reason": mapping.reason,
            "start_close_paise": by_session[window.start_session],
            "end_close_paise": by_session[window.end_session],
            "price_only_return": price_return,
            "original_weight_contribution": position.weight * price_return,
            "action_coverage": "UNKNOWN_INCOMPLETE_SOURCE; no factor imputed",
        }
        components.append(row)
        supported.append((position, mapping, by_session))

    supported_weight = sum(position.weight for position, _mapping, _series_ in supported)
    unmatched_weight = round(unmatched_weight, 15)
    if supported_weight <= 0:
        return CrisisReplayResult(
            event=asdict(event), window=asdict(window), snapshot_hash=snapshot.semantic_hash,
            mapping_hash=semantic_sha256([asdict(item) for item in mappings]),
            assumptions=asdict(assumptions), status="DATA_BLOCKED_NO_SUPPORTED_COMPONENTS",
            output_label="HISTORICAL_RETROSPECTIVE", supported_weight=0.0,
            unmatched_weight=1.0, expected_sessions=len(expected_stress),
            observed_common_sessions=0, observed_session_coverage=0.0,
            component_results=tuple(components), supported_components_return=None,
            full_portfolio_return=None, peak_to_trough_drawdown=None,
            drawdown_peak_session=None, drawdown_trough_session=None,
            worst_observed_day=None,
            recovery={"status": "UNAVAILABLE", "reason": "no supported price path"},
            sector_contributions=(), benchmark=_benchmark(conn, assumptions, window),
            data_quality="INSUFFICIENT",
            limitations=tuple(limitations),
            prohibited_interpretations=("FORECAST", "FUTURE_PROBABILITY", "EXPECTED_RETURN",
                                        "LIVE_EXECUTABLE"),
        )

    common_sessions = set(_expected_sessions(
        conn, window.start_session, window.recovery_observation_end))
    for _position, _mapping, values in supported:
        common_sessions &= set(values)
    ordered_common = sorted(common_sessions)
    stress_sessions = [session for session in ordered_common if session <= window.end_session]
    path = []
    for session in ordered_common:
        value = sum(
            (position.weight / supported_weight)
            * (values[session] / values[window.start_session])
            for position, _mapping, values in supported
        )
        path.append((session, value))
    stress_path = [(session, value) for session, value in path if session <= window.end_session]
    coverage = len(stress_sessions) / len(expected_stress)
    drawdown, peak_session, trough_session = _drawdown(stress_path)
    worst_day = _worst_day(stress_path)
    supported_return = stress_path[-1][1] / stress_path[0][1] - 1.0

    peak_value = next(value for session, value in stress_path if session == peak_session)
    post_trough = [(session, value) for session, value in path if session > trough_session]
    recovered = next(((session, value) for session, value in post_trough if value >= peak_value), None)
    if recovered:
        recovery = {
            "status": "OBSERVED", "recovery_session": recovered[0],
            "sessions_after_trough": sum(1 for session, _ in path
                                          if trough_session < session <= recovered[0]),
            "basis": "supported-components raw price-only index",
        }
    else:
        recovery = {
            "status": "NOT_OBSERVED_BY_CUTOFF",
            "observation_end": window.recovery_observation_end,
            "basis": "supported-components raw price-only index",
        }

    by_sector: dict[str, float] = {}
    for row in components:
        if row["status"] == "OBSERVED_PRICE_ONLY" and row.get("sector"):
            by_sector[row["sector"]] = by_sector.get(row["sector"], 0.0) \
                + row["original_weight_contribution"]
    sector_rows = tuple(
        {"sector": sector, "original_weight_price_contribution": contribution}
        for sector, contribution in sorted(by_sector.items())
    )
    if unmatched_weight:
        limitations.append(
            f"{unmatched_weight:.6f} portfolio weight unmatched; no full-portfolio return computed")
    quality = "LOW_PRICE_ONLY_ACTION_COVERAGE_UNKNOWN"
    has_proxy = any(mapping.mapping_kind in {"SECTOR_PROXY", "INDEX_PROXY"}
                    for _position, mapping, _series in supported)
    if has_proxy:
        status = "PARTIAL_PRICE_ONLY_PROXY"
    elif unmatched_weight:
        status = "PARTIAL_PRICE_ONLY_UNMATCHED"
    else:
        status = "PRICE_ONLY_COMPLETE_MAPPING"
    if coverage < assumptions.coverage_threshold:
        status = "DATA_BLOCKED_INSUFFICIENT_SESSION_COVERAGE"
        quality = "INSUFFICIENT"

    return CrisisReplayResult(
        event=asdict(event), window=asdict(window), snapshot_hash=snapshot.semantic_hash,
        mapping_hash=semantic_sha256([asdict(item) for item in mappings]),
        assumptions=asdict(assumptions), status=status,
        output_label="HISTORICAL_RETROSPECTIVE", supported_weight=supported_weight,
        unmatched_weight=unmatched_weight, expected_sessions=len(expected_stress),
        observed_common_sessions=len(stress_sessions), observed_session_coverage=coverage,
        component_results=tuple(components), supported_components_return=supported_return,
        full_portfolio_return=None, peak_to_trough_drawdown=drawdown,
        drawdown_peak_session=peak_session, drawdown_trough_session=trough_session,
        worst_observed_day=worst_day, recovery=recovery,
        sector_contributions=sector_rows, benchmark=_benchmark(conn, assumptions, window),
        data_quality=quality, limitations=tuple(limitations),
        prohibited_interpretations=("FORECAST", "FUTURE_PROBABILITY", "EXPECTED_RETURN",
                                    "LIVE_EXECUTABLE"),
    )
