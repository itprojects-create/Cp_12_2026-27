"""Wave 6 forward-only contracts, accounting fixtures and operations tests.

All observations and fills in this file are ENGINEERING_FIXTURE.  No test uses
the internet, a provider credential, the user paper book, Jev, Mercury, or a
broker endpoint.
"""
from __future__ import annotations

import json
import os
import threading
import importlib.util
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quantplus_intelligence.research_v3.forward.benchmarks import (
    VERDICT_DATA_BLOCKED,
    VERDICT_DATA_BLOCKED_BASIS_MISMATCH,
    VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE,
    absolute_economics,
    benchmark_relative,
    brier_scores,
    rank_ic_by_date,
    result_panels,
    sample_sufficiency,
)
from quantplus_intelligence.research_v3.forward.contracts import (
    ADMISSIBILITY_NO_ELIGIBLE_STRATEGY,
    ADMISSIBILITY_OPERATOR_APPROVAL_REQUIRED,
    ADMISSIBILITY_PAPER_ELIGIBLE,
    ADMISSIBILITY_RESEARCH_ONLY,
    DECISION_ABSTAIN,
    DECISION_ELIGIBILITY_FAILURE,
    DECISION_NO_SIGNAL,
    DECISION_SIGNAL,
    FILL_NOT_EXECUTED,
    FILL_PARTIAL,
    MATURITY_ELIGIBLE_PAPER,
    MATURITY_ENGINEERING_FIXTURE,
    MATURITY_OBSERVED_FORWARD,
    AbstentionRecord,
    CorporateActionEvent,
    FillEvent,
    JobReceiptRecord,
    OutcomeObservation,
    PaperIntent,
    PreflightRecord,
    QuoteObservation,
    SessionLock,
    SignalDecision,
    ValuationMark,
)
from quantplus_intelligence.research_v3.forward.fee_sources import (
    broker_component,
    fee_gate,
)
from quantplus_intelligence.research_v3.forward.ledger import (
    GENESIS,
    ForwardLedger,
    LedgerIntegrityError,
    SqliteForwardLedger,
)
from quantplus_intelligence.research_v3.forward.paper_book import ResearchPaperBook
from quantplus_intelligence.research_v3.forward.preregistration import (
    ForwardProtocol,
    OperatorApproval,
    admissibility,
    mint_new_stream,
    seal_protocol,
)
from quantplus_intelligence.research_v3.forward.signals import SignalPipeline, pit_value
from quantplus_intelligence.research_v3.forward.worker import ClockSkewError, ForwardWorker
from quantplus_intelligence.research_v3.wave6 import health_endpoint, stream_status

UTC = timezone.utc
SEAL_UTC = "2026-11-14T15:00:00+00:00"
SEAL_IST = "2026-11-14T20:30:00+05:30"
DECISION = "2026-11-16T04:00:00+00:00"
RECORDED = "2026-11-16T04:00:01+00:00"
ISIN = "INE467B01029"
SHA_A = "a" * 64


def protocol(*, stream="w6-null-v1", candidate=False, approved=False,
             broker_plan=None, capital=None) -> ForwardProtocol:
    approval = (OperatorApproval(
        approval_id="operator-fixture-approval", scope="paper_only",
        granted_at="2026-11-14T14:59:00+00:00") if approved else None)
    return ForwardProtocol(
        experiment_id="quantplus-w6-forward-null-v1",
        stream_id=stream,
        preregistered_at_utc=SEAL_UTC,
        preregistered_at_ist=SEAL_IST,
        strategy_family="fixture" if candidate else None,
        strategy_spec_hash=SHA_A if candidate else None,
        model_family="fixture" if candidate else None,
        model_version="fixture-v1" if candidate else None,
        model_artifact_hash=SHA_A if candidate else None,
        hypothesis=("fixture candidate" if candidate else
                    "Null baseline: log no trade until a candidate passes every gate"),
        benchmarks=("CASH", "NIFTY50_TRI_IF_VERIFIED"),
        universe_rule="FIXTURE_TCS_ONLY" if candidate else "NULL_BASELINE_NO_UNIVERSE",
        event_ai_components="OFF",
        initial_virtual_capital_paise=capital,
        max_position_weight=0.2 if capital else None,
        max_positions=5 if capital else None,
        operator_approval=approval,
        broker_plan=broker_plan,
        allowed_data_sources=("fixture",),
        source_rights={
            "market_data": "ENGINEERING_FIXTURE_ONLY",
            "corporate_actions": "ENGINEERING_FIXTURE_ONLY",
            "fee_plan": "PUBLIC_REFERENCE_CURRENT_ONLY",
            "benchmark": "NOT_CONFIGURED",
        },
        no_trade_conditions=("NO_ELIGIBLE_STRATEGY", "OPERATOR_APPROVAL_REQUIRED"),
    )


def sealed_ledger(tmp_path, *, stream="w6-null-v1", candidate=False,
                  approved=False, broker_plan=None, capital=None):
    ledger = ForwardLedger(tmp_path / "forward.jsonl")
    p = protocol(stream=stream, candidate=candidate, approved=approved,
                 broker_plan=broker_plan, capital=capital)
    seal_protocol(p, ledger, SEAL_UTC)
    return ledger, p


def decision(*, side="BUY", symbol="TCS", cutoff=DECISION):
    return SignalDecision(
        stream_id="fixture-stream", recorded_at=RECORDED,
        maturity=MATURITY_ENGINEERING_FIXTURE, decision_cutoff=cutoff,
        session_date="2026-11-16", symbol=symbol, isin=ISIN,
        candidate_id="fixture-candidate", strategy_spec_hash=SHA_A,
        model_version="fixture-v1", decision=DECISION_SIGNAL, side=side,
        target_weight=0.1, horizon_sessions=20, score=0.2,
        calendar_version="nse-cm-2026.2")


def quote(*, stream="fixture-stream", at="2026-11-16T04:30:00+00:00",
          provider_ts="2026-11-16T04:29:50+00:00", available_at=None,
          session="2026-11-16", bid=9_990, ask=10_010, volume=10_000,
          depth=100, stale=False, halted=False, symbol="TCS"):
    return QuoteObservation(
        stream_id=stream, recorded_at=at,
        maturity=MATURITY_ENGINEERING_FIXTURE, session_date=session,
        symbol=symbol, isin=ISIN, provider="fixture",
        provider_ts=provider_ts, available_at=available_at or provider_ts,
        bid_paise=bid, ask_paise=ask, last_paise=10_000,
        volume=volume, depth_lots=depth, stale=stale,
        halted_or_suspended=halted, source_ref="fixture://quote",
        source_sha256=SHA_A)


def intent(*, intent_id="fixture-intent-0001", side="BUY", quantity=10,
           order_type="MARKET", limit=None, stop=None, notional=200_000,
           oco=None, decision_record=None, session="2026-11-16",
           recorded_at=RECORDED):
    return PaperIntent(
        stream_id="fixture-stream", recorded_at=recorded_at,
        maturity=MATURITY_ENGINEERING_FIXTURE, decision_cutoff=DECISION,
        session_date=session, intent_id=intent_id, symbol="TCS",
        isin=ISIN, side=side, order_type=order_type, quantity=quantity,
        notional_paise=notional, limit_paise=limit, stop_paise=stop,
        oco_group=oco, decision=decision_record or decision(side=side))


def fixture_book(tmp_path, *, initial=10_000_000, participation=0.05,
                 broker_plan="fyers_standard_observed_2026_11_14"):
    ledger = ForwardLedger(tmp_path / "fixture-ledger.jsonl")
    p = protocol(stream="fixture-stream", candidate=True, broker_plan=broker_plan)
    seal_protocol(p, ledger, SEAL_UTC)
    book = ResearchPaperBook(
        ledger, "fixture-stream", p, fixture=True,
        initial_cash_paise=initial,
        max_participation_fraction=participation)
    book.register_instrument("TCS", ISIN)
    return book, ledger, p


def fill_buy_and_settle(book, quantity=10, intent_id="fixture-buy-0001"):
    accepted = book.submit_intent(intent(intent_id=intent_id, quantity=quantity,
                                         notional=quantity * 12_000))
    assert accepted["accepted"]
    fills = book.observe_quote(quote(depth=quantity + 10))
    assert fills and fills[0]["filled_quantity"] == quantity
    settled = book.settle("2026-11-17")
    assert settled["shares_settled_buy"] == quantity


# ---------------------------------------------------------------------------
# preregistration and immutable records
# ---------------------------------------------------------------------------

def test_protocol_hash_is_canonical_and_timestamp_pair_is_same_instant():
    a = protocol()
    b = protocol()
    assert a.content_address() == b.content_address()
    with pytest.raises(ValueError, match="same instant"):
        replace(a, preregistered_at_ist="2026-11-14T20:31:00+05:30")


def test_protocol_utc_storage_and_operator_owned_sizing():
    with pytest.raises(ValueError, match="must be UTC"):
        replace(protocol(), preregistered_at_utc=SEAL_IST,
                preregistered_at_ist=SEAL_IST)
    with pytest.raises(ValueError, match="require an operator approval"):
        protocol(capital=10_000_000)


def test_seal_is_first_event_and_idempotent(tmp_path):
    ledger, p = sealed_ledger(tmp_path)
    second = seal_protocol(p, ledger, SEAL_UTC)
    assert second.is_new_stream is False
    assert len(ledger.records()) == 1
    assert ledger.records()[0]["payload"]["content_hash"] == p.content_address()


def test_post_seal_edit_same_stream_refused_and_new_stream_preserves_prior(tmp_path):
    ledger, p = sealed_ledger(tmp_path)
    changed = replace(p, hypothesis="changed after seal")
    with pytest.raises(PermissionError, match="different stream_id"):
        seal_protocol(changed, ledger, SEAL_UTC)
    new = mint_new_stream(
        p, "w6-null-v2", "2026-11-14T15:01:00+00:00",
        "2026-11-14T20:31:00+05:30")
    assert new.stream_id != p.stream_id
    assert new.prior_version_link == p.content_address()
    assert ledger.records()[0]["payload"]["stream_id"] == p.stream_id


def test_mint_requires_different_stream_id():
    with pytest.raises(ValueError, match="distinct"):
        mint_new_stream(protocol(), "w6-null-v1", SEAL_UTC, SEAL_IST)


def test_null_and_candidate_admissibility_are_code_owned():
    null = admissibility(protocol())
    assert null["status"] == ADMISSIBILITY_NO_ELIGIBLE_STRATEGY
    assert null["paper_intent_allowed"] is False
    research = admissibility(protocol(candidate=True))
    assert research["status"] == ADMISSIBILITY_RESEARCH_ONLY
    assert "NO_PROVEN_NET_ALPHA_GROSS_ONLY_DIAGNOSTIC" in research["reasons"]


def test_all_integrity_gates_still_require_operator_approval():
    p = protocol(candidate=True)
    gate = admissibility(
        p, holdout_is_untouched=True, net_returns_available=True,
        fee_plan_verified=True, corporate_actions_verified=True,
        benchmark_verified=True)
    assert gate["status"] == ADMISSIBILITY_OPERATOR_APPROVAL_REQUIRED
    approved = protocol(candidate=True, approved=True, capital=10_000_000)
    gate = admissibility(
        approved, holdout_is_untouched=True, net_returns_available=True,
        fee_plan_verified=True, corporate_actions_verified=True,
        benchmark_verified=True, operator_approval_on_file=True)
    assert gate["status"] == ADMISSIBILITY_PAPER_ELIGIBLE


def test_real_quote_requires_complete_provenance_and_fixture_provider_is_forbidden():
    with pytest.raises(ValueError, match="require provider"):
        QuoteObservation(
            stream_id="real", recorded_at=RECORDED,
            maturity=MATURITY_OBSERVED_FORWARD, symbol="TCS",
            provider="fyers", last_paise=10_000)
    with pytest.raises(ValueError, match="fixture provider"):
        QuoteObservation(
            stream_id="real", recorded_at=RECORDED,
            maturity=MATURITY_OBSERVED_FORWARD, symbol="TCS",
            provider="fixture", provider_ts=RECORDED, available_at=RECORDED,
            last_paise=10_000, source_ref="x", source_sha256=SHA_A)


def test_paper_intent_references_decision_without_embedding_outcome():
    d = decision()
    payload = intent(decision_record=d).payload()
    assert payload["decision_ref"] == d.decision_id
    assert "outcome" not in json.dumps(payload).lower()


def test_outcome_attaches_only_after_cutoff():
    out = OutcomeObservation(
        stream_id="fixture-stream", recorded_at="2026-11-17T04:00:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, decision_cutoff=DECISION,
        decision_ref=decision().decision_id, outcome_kind="RETURN",
        value=0.01, observed_at="2026-11-17T03:59:00+00:00",
        source_id="fixture", source_sha256=SHA_A)
    assert out.payload()["value"] == 0.01
    with pytest.raises(ValueError, match="after the decision cutoff"):
        replace(out, observed_at=DECISION)


def test_executed_fill_requires_stable_fill_id():
    with pytest.raises(ValueError, match="fill_id"):
        FillEvent(
            stream_id="fixture", recorded_at=RECORDED,
            maturity=MATURITY_ENGINEERING_FIXTURE,
            intent_id="i", symbol="TCS", side="BUY", quantity=1,
            price_paise=100, fill_status="FILLED", filled_quantity=1)


def test_preflight_and_job_receipt_are_typed():
    preflight = PreflightRecord(
        stream_id="s", recorded_at=RECORDED,
        maturity=MATURITY_ENGINEERING_FIXTURE, check_id="p1", status="PASS",
        code_hash=SHA_A, calendar_version="nse-cm-2026.2",
        rights_status="FIXTURE", fee_status="FIXTURE",
        action_status="FIXTURE", benchmark_status="DATA_BLOCKED")
    receipt = JobReceiptRecord(
        stream_id="s", recorded_at=RECORDED,
        maturity=MATURITY_ENGINEERING_FIXTURE, receipt_id="r1",
        job="session_lock", status="OK")
    assert preflight.payload()["record_kind"] == "PREFLIGHT"
    assert receipt.payload()["record_kind"] == "JOB_RECEIPT"


# ---------------------------------------------------------------------------
# append-only ledger, concurrency and crash recovery
# ---------------------------------------------------------------------------

def test_ledger_exactly_once_and_conflicting_reuse(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    payload = {"stream_id": "s", "x": 1}
    first, added = ledger.append("RISK_EVENT", RECORDED, payload, {"k": 1})
    replay, added2 = ledger.append("RISK_EVENT", RECORDED, payload, {"k": 1})
    assert added and not added2 and replay == first and len(ledger.records()) == 1
    with pytest.raises(LedgerIntegrityError, match="IDEMPOTENCY_CONFLICT"):
        ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s", "x": 2}, {"k": 1})


def test_ledger_tamper_is_detected_and_blocks_append(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s"}, {"k": 1})
    row = json.loads(ledger.path.read_text(encoding="utf-8"))
    row["payload"]["tampered"] = True
    ledger.path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert ledger.verify_chain()[0] is False
    with pytest.raises(LedgerIntegrityError, match="invalid chain"):
        ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s"}, {"k": 2})


def test_concurrent_identical_append_occurs_once(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    errors = []
    def write():
        try:
            ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s"}, {"same": 1})
        except Exception as exc:  # pragma: no cover - assertion below
            errors.append(exc)
    threads = [threading.Thread(target=write) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(ledger.records()) == 1 and ledger.verify_chain()[0]


def test_concurrent_unique_writers_have_monotonic_chain(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    threads = [threading.Thread(
        target=lambda i=i: ledger.append(
            "RISK_EVENT", RECORDED, {"stream_id": "s", "i": i}, {"i": i}))
        for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [row["seq"] for row in ledger.records()] == list(range(1, 11))
    assert ledger.verify_chain() == (True, "chain intact")


def test_torn_invalid_tail_is_removed_without_rewriting_survivors(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    record, _ = ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s"}, {"i": 1})
    survivor = ledger.path.read_bytes()
    with ledger.path.open("ab") as handle:
        handle.write(b'{"torn":')
    ok, reason = ledger.truncate_torn_tail()
    assert ok and "torn tail removed" in reason
    assert ledger.path.read_bytes() == survivor
    assert ledger.head() == record["record_hash"]


def test_complete_tail_without_newline_is_preserved(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s"}, {"i": 1})
    ledger.path.write_bytes(ledger.path.read_bytes().rstrip(b"\n"))
    ok, reason = ledger.truncate_torn_tail()
    assert ok and "preserved" in reason
    assert len(ledger.records()) == 1


def test_stream_status_reports_seal_before_first_event(tmp_path):
    ledger, _ = sealed_ledger(tmp_path)
    lock = SessionLock(
        stream_id="w6-null-v1", recorded_at="2026-11-16T04:00:01+00:00",
        maturity=MATURITY_OBSERVED_FORWARD, session_date="2026-11-16",
        decision_cutoff=DECISION, calendar_verified=True,
        provider_status="NOT_CONFIGURED")
    ledger.append_record("SESSION_LOCK", lock, {"session": "2026-11-16"})
    status = stream_status(ledger, "w6-null-v1")
    assert status["sealed_before_first_signal"] and status["chain_intact"]


def test_ledger_refuses_backdated_append_after_newer_head(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    ledger.append("RISK_EVENT", "2026-11-16T05:00:00+00:00",
                  {"stream_id": "s"}, {"i": 1})
    with pytest.raises(LedgerIntegrityError, match="TIMESTAMP_REGRESSION"):
        ledger.append("RISK_EVENT", "2026-11-16T04:59:59+00:00",
                      {"stream_id": "s"}, {"i": 2})


def test_transactional_sqlite_ledger_concurrent_writers_and_jsonl_export(tmp_path):
    ledger = SqliteForwardLedger(tmp_path / "forward.sqlite3")
    errors = []
    def write(index):
        try:
            ledger.append("RISK_EVENT", RECORDED,
                          {"stream_id": "s", "index": index}, {"index": index})
        except Exception as exc:  # pragma: no cover - assertion below
            errors.append(exc)
    threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(ledger.records()) == 12
    assert ledger.verify_chain() == (True, "chain intact")
    exported = ledger.export_jsonl(tmp_path / "forward.jsonl")
    audit = ForwardLedger(exported)
    assert audit.records() == ledger.records() and audit.verify_chain()[0]


def test_transactional_sqlite_ledger_exactly_once_and_rollback_recovery(tmp_path):
    ledger = SqliteForwardLedger(tmp_path / "forward.sqlite3")
    payload = {"stream_id": "s", "value": 1}
    _, added = ledger.append("RISK_EVENT", RECORDED, payload, {"same": 1})
    _, replayed = ledger.append("RISK_EVENT", RECORDED, payload, {"same": 1})
    assert added and not replayed and len(ledger.records()) == 1
    conn = ledger._connect()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO forward_events VALUES (?,?,?,?,?,?,?)",
        (2, "crash", "RISK_EVENT", RECORDED, "s", "{}", "bad"))
    conn.close()  # SQLite rolls the uncommitted crash simulation back.
    assert len(ledger.records()) == 1 and ledger.verify_chain()[0]


def test_transactional_sqlite_readonly_verification_detects_tamper(tmp_path):
    ledger = SqliteForwardLedger(tmp_path / "forward.sqlite3")
    ledger.append("RISK_EVENT", RECORDED, {"stream_id": "s"}, {"i": 1})
    conn = ledger._connect()
    try:
        row = json.loads(conn.execute(
            "SELECT record_json FROM forward_events WHERE seq=1").fetchone()[0])
        row["payload"]["tamper"] = True
        conn.execute("UPDATE forward_events SET record_json=? WHERE seq=1",
                     (json.dumps(row, sort_keys=True),))
    finally:
        conn.close()
    assert ledger.verify_chain()[0] is False


# ---------------------------------------------------------------------------
# every-candidate signal logging and PIT gates
# ---------------------------------------------------------------------------

def test_signal_pipeline_refuses_unsealed_stream(tmp_path):
    ledger = ForwardLedger(tmp_path / "ledger.jsonl")
    pipeline = SignalPipeline(ledger, "s", None, fixture=True)
    with pytest.raises(PermissionError, match="STREAM_NOT_SEALED"):
        pipeline.evaluate([{"symbol": "TCS"}], DECISION, "2026-11-16",
                          recorded_at=RECORDED)


def test_null_pipeline_records_every_universe_candidate_as_no_signal(tmp_path):
    ledger, p = sealed_ledger(tmp_path)
    pipeline = SignalPipeline(ledger, p.stream_id, p, fixture=True)
    rows = pipeline.evaluate(
        [{"symbol": "TCS", "isin": ISIN}, {"symbol": "INFY", "isin": "INE009A01021"}],
        DECISION, "2026-11-16", recorded_at=RECORDED)
    assert len(rows) == 2
    assert all(row["record_kind"] == "NO_SIGNAL" for row in rows)
    assert len(ledger.stream_records(p.stream_id, "NO_SIGNAL")) == 2


def test_mixed_signal_abstention_failure_and_no_signal_are_all_retained(tmp_path):
    ledger, p = sealed_ledger(tmp_path, candidate=True)
    def evaluator(candidate, cutoff):
        del cutoff
        return candidate["answer"]
    candidates = [
        {"symbol": "A", "answer": {"decision": DECISION_SIGNAL, "side": "BUY",
                                     "horizon_sessions": 20}},
        {"symbol": "B", "answer": {"decision": DECISION_ABSTAIN,
                                     "answerable": False}},
        {"symbol": "C", "answer": {"decision": DECISION_ELIGIBILITY_FAILURE,
                                     "blocker": "UNKNOWN_ISIN"}},
        {"symbol": "D", "answer": {"decision": DECISION_NO_SIGNAL}},
    ]
    rows = SignalPipeline(ledger, p.stream_id, p, evaluator, fixture=True).evaluate(
        candidates, DECISION, "2026-11-16", recorded_at=RECORDED)
    assert [row["record_kind"] for row in rows] == [
        "SIGNAL_DECISION", "ABSTENTION", "ELIGIBILITY_FAILURE", "NO_SIGNAL"]


def test_signal_recorded_at_cannot_be_backdated():
    ledger = ForwardLedger(Path(os.devnull))
    del ledger
    with pytest.raises(ValueError, match="cannot precede"):
        # Build a real temporary ledger through pytest's temp path in the next test;
        # this assertion exercises the clock relation directly on the record.
        SignalDecision(
            stream_id="s", recorded_at="2026-11-16T03:59:59+00:00",
            decision_cutoff=DECISION, symbol="TCS", decision=DECISION_NO_SIGNAL)


def test_pit_value_blocks_delayed_news_and_future_bars():
    assert pit_value(10, available_at=DECISION, decision_cutoff=DECISION,
                     source_id="bar") == 10
    with pytest.raises(ValueError, match="FUTURE_INPUT_BLOCKED:news"):
        pit_value("headline", available_at="2026-11-16T04:00:01+00:00",
                  decision_cutoff=DECISION, source_id="news")


# ---------------------------------------------------------------------------
# exact paper-account engineering fixtures (never real evidence)
# ---------------------------------------------------------------------------

def test_nonfixture_python_book_is_forbidden_second_engine(tmp_path):
    ledger, p = sealed_ledger(tmp_path, candidate=True, approved=True,
                              capital=10_000_000)
    with pytest.raises(PermissionError, match="AUTHORITATIVE_ENGINE_REQUIRED"):
        ResearchPaperBook(ledger, p.stream_id, p, fixture=False)


def test_unknown_isin_and_market_buy_without_reservation_fail_closed(tmp_path):
    book, _, _ = fixture_book(tmp_path)
    unknown = replace(intent(), isin=None, symbol="UNKNOWN")
    assert book.submit_intent(unknown)["status"] == "REJECTED"
    no_reserve = intent(intent_id="fixture-noreserve", notional=None)
    assert book.submit_intent(no_reserve)["status"] == FILL_NOT_EXECUTED


def test_next_observed_quote_only_and_duplicate_trigger_cannot_double_fill(tmp_path):
    book, ledger, _ = fixture_book(tmp_path)
    assert book.submit_intent(intent())["accepted"]
    old = quote(available_at=DECISION, provider_ts=DECISION)
    assert book.observe_quote(old)[0]["status"] == FILL_NOT_EXECUTED
    fresh = quote(at="2026-11-16T04:30:01+00:00",
                  provider_ts="2026-11-16T04:29:55+00:00")
    assert book.observe_quote(fresh)[0]["filled_quantity"] == 10
    assert book.observe_quote(fresh) == []
    executed = [row for row in ledger.stream_records("fixture-stream", "FILL_EVENT")
                if row["payload"]["fill_status"] in ("FILLED", "PARTIAL_FILL")]
    assert len(executed) == 1


def test_stale_halted_holiday_and_wrong_symbol_quotes_never_fill(tmp_path):
    variants = [
        quote(stale=True), quote(halted=True),
        quote(session="2026-11-24", at="2026-11-24T04:30:00+00:00",
              provider_ts="2026-11-24T04:29:50+00:00"),
        quote(symbol="INFY"),
    ]
    for index, observed in enumerate(variants):
        book, _, _ = fixture_book(tmp_path / str(index))
        book.submit_intent(intent(intent_id=f"fixture-block-{index:04d}"))
        outcome = book.observe_quote(observed)
        assert not outcome or outcome[0]["status"] == FILL_NOT_EXECUTED
        assert not book.positions


def test_market_partial_fill_cancels_remainder_like_existing_engine(tmp_path):
    book, ledger, _ = fixture_book(tmp_path, participation=1.0)
    book.submit_intent(intent(quantity=10, notional=200_000))
    outcome = book.observe_quote(quote(depth=3, volume=3))
    assert outcome[0]["status"] == FILL_PARTIAL
    assert outcome[0]["filled_quantity"] == 3
    assert not book.open_orders
    statuses = [row["payload"]["fill_status"]
                for row in ledger.stream_records("fixture-stream", "FILL_EVENT")]
    assert statuses[-2:] == ["PARTIAL_FILL", "CANCELLED"]


def test_limit_and_stop_conditions_do_not_invent_fills(tmp_path):
    book, _, _ = fixture_book(tmp_path)
    book.submit_intent(intent(intent_id="fixture-limit-0001", order_type="LIMIT",
                              limit=9_900, notional=None))
    assert book.observe_quote(quote())[0]["status"] == FILL_NOT_EXECUTED
    book2, _, _ = fixture_book(tmp_path / "stop")
    book2.submit_intent(intent(intent_id="fixture-stop-0001", order_type="STOP",
                               stop=10_500))
    assert book2.observe_quote(quote()) == []
    assert not book2.positions


def test_fees_use_executed_notional_and_cash_reconciles(tmp_path):
    book, ledger, _ = fixture_book(tmp_path, participation=1.0)
    book.submit_intent(intent(quantity=10, notional=500_000))
    result = book.observe_quote(quote(depth=4, volume=4))[0]
    fill = next(row["payload"] for row in ledger.stream_records(
        "fixture-stream", "FILL_EVENT") if row["payload"]["fill_status"] == "PARTIAL_FILL")
    fee = ledger.stream_records("fixture-stream", "FEE_EVENT")[0]["payload"]
    assert fill["executed_value_paise"] == 4 * 10_010
    assert fee["fill_ref"] == fill["fill_id"]
    assert result["fees_paise"] == fee["total_paise"]
    assert book.reconcile()["ok"]


def test_t1_reservations_settlement_dp_once_per_isin_day_and_cash_conservation(tmp_path):
    book, ledger, _ = fixture_book(tmp_path, participation=1.0)
    fill_buy_and_settle(book, 10)
    assert book.positions[ISIN].settled_qty == 10
    for index, qty in enumerate((3, 2), start=1):
        intent_minute = 30 + (index - 1) * 2
        quote_minute = intent_minute + 1
        sell = intent(intent_id=f"fixture-sell-{index:04d}", side="SELL",
                      quantity=qty, notional=None,
                      decision_record=decision(side="SELL"),
                      session="2026-11-18",
                      recorded_at=f"2026-11-18T04:{intent_minute:02d}:00+00:00")
        assert book.submit_intent(sell)["accepted"]
        observed = quote(
            at=f"2026-11-18T04:{quote_minute:02d}:00+00:00",
            provider_ts=f"2026-11-18T04:{quote_minute:02d}:00+00:00",
            session="2026-11-18", depth=20)
        assert book.observe_quote(observed)[0]["filled_quantity"] == qty
    fees = [row["payload"] for row in ledger.stream_records("fixture-stream", "FEE_EVENT")]
    dp = [sum(item["amount_paise"] for item in row["items"] if item["code"] == "DP")
          for row in fees if any(item["code"] == "DP" for item in row["items"])]
    assert sum(value > 0 for value in dp) == 1
    before = book.cash_paise
    assert book.pending_proceeds_paise > 0
    settlement = book.settle("2026-11-19")
    assert settlement["proceeds_credited_paise"] > 0
    assert book.cash_paise > before and book.pending_proceeds_paise == 0
    assert book.reconcile()["ok"]


def test_oco_sell_legs_share_reservation_and_first_fill_cancels_sibling(tmp_path):
    book, ledger, _ = fixture_book(tmp_path, participation=1.0)
    fill_buy_and_settle(book, 5)
    stop = intent(intent_id="fixture-oco-stop", side="SELL", quantity=5,
                  order_type="STOP", stop=9_900, notional=None, oco="g1",
                  decision_record=decision(side="SELL"), session="2026-11-18",
                  recorded_at="2026-11-18T04:30:00+00:00")
    target = intent(intent_id="fixture-oco-target", side="SELL", quantity=5,
                    order_type="LIMIT", limit=10_050, notional=None, oco="g1",
                    decision_record=decision(side="SELL"), session="2026-11-18",
                    recorded_at="2026-11-18T04:30:00+00:00")
    assert book.submit_intent(stop)["accepted"]
    assert book.submit_intent(target)["accepted"]
    observed = quote(at="2026-11-18T04:31:00+00:00",
                     provider_ts="2026-11-18T04:30:59+00:00",
                     session="2026-11-18", bid=10_100, ask=10_110)
    book.observe_quote(observed)
    assert not book.open_orders
    assert any(REASON == "OCO_OTHER_LEG_FILLED"
               for row in ledger.stream_records("fixture-stream", "FILL_EVENT")
               for REASON in row["payload"]["reason_codes"])


def test_verified_split_bonus_dividend_and_unknown_action_block(tmp_path):
    book, _, _ = fixture_book(tmp_path, participation=1.0)
    fill_buy_and_settle(book, 10)
    split = CorporateActionEvent(
        stream_id="fixture-stream", recorded_at="2026-11-17T10:00:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, symbol="TCS", isin=ISIN,
        action_kind="SPLIT", effective_session="2026-11-17", factor=2.0,
        status="APPLIED", source_ref="fixture://action")
    assert book.apply_corporate_action(split)["new_qty"] == 20
    bonus = replace(split, recorded_at="2026-11-18T10:00:00+00:00",
                    action_kind="BONUS", effective_session="2026-11-18",
                    factor=1.5)
    assert book.apply_corporate_action(bonus)["new_qty"] == 30
    dividend = replace(
        split, recorded_at="2026-11-19T10:00:00+00:00",
        action_kind="DIVIDEND", effective_session="2026-11-19",
        factor=None, dividend_per_share_paise=250)
    assert book.apply_corporate_action(dividend)["credit_paise"] == 7_500
    blocked = replace(
        split, recorded_at="2026-11-20T10:00:00+00:00",
        action_kind="SPLIT", effective_session="2026-11-20",
        factor=None, status="BLOCKED_UNVERIFIED_SOURCE")
    assert book.apply_corporate_action(blocked)["position_blocked"] is True


def test_known_and_unknown_demerger_are_explicit(tmp_path):
    book, _, _ = fixture_book(tmp_path, participation=1.0)
    fill_buy_and_settle(book, 10)
    known = CorporateActionEvent(
        stream_id="fixture-stream", recorded_at="2026-11-18T10:00:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, symbol="TCS", isin=ISIN,
        action_kind="DEMERGER", effective_session="2026-11-18", status="APPLIED",
        child_symbol="TCSCHILD", child_isin="INE000000001",
        child_quantity_factor=0.5, child_cost_allocation_fraction=0.2,
        source_ref="fixture://demerger")
    result = book.apply_corporate_action(known)
    assert result["applied"] and result["child_quantity"] == 5
    unknown = replace(known, recorded_at="2026-11-19T10:00:00+00:00",
                      status="BLOCKED_UNVERIFIED_SOURCE",
                      child_symbol=None, child_isin=None,
                      child_quantity_factor=None, child_cost_allocation_fraction=None)
    assert book.apply_corporate_action(unknown)["position_blocked"]


def test_nav_requires_complete_observed_marks_and_reports_paise_pnl(tmp_path):
    book, _, _ = fixture_book(tmp_path, participation=1.0)
    fill_buy_and_settle(book, 2)
    assert book.nav()["nav_known"] is False
    mark = ValuationMark(
        stream_id="fixture-stream", recorded_at="2026-11-17T10:00:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, session_date="2026-11-17",
        symbol="TCS", isin=ISIN, quantity=2, mark_paise=10_100,
        mark_source="fixture", mark_time="2026-11-17T09:59:59+00:00")
    assert book.mark_position(mark)["marked"]
    nav = book.nav("2026-11-17")
    assert nav["nav_known"] and isinstance(nav["equity_paise"], int)
    assert nav["unrealised_pnl_paise"] == 2 * (10_100 - 10_010)
    assert book.reconcile()["ok"]


def test_fee_source_gate_never_backdates_or_confuses_account_plan():
    with pytest.raises(ValueError, match="no component effective"):
        broker_component("fyers_standard_observed_2026_11_14",
                         "2026-11-13T10:00:00+00:00")
    gate = fee_gate("fyers_standard_observed_2026_11_14", RECORDED,
                    corporate_action_source_ready=False,
                    account_plan_confirmed=False)
    assert gate["status"] == "DATA_BLOCKED"
    assert gate["fixture_calculation_allowed"]
    assert gate["historical_extrapolation_allowed"] is False


# ---------------------------------------------------------------------------
# benchmarks, honest labels and tiny-sample handling
# ---------------------------------------------------------------------------

def test_rank_ic_clusters_by_date_not_stock_rows():
    rows = [
        {"session_date": "2026-11-16", "score": 1, "forward_return": 0.01},
        {"session_date": "2026-11-16", "score": 2, "forward_return": 0.02},
        {"session_date": "2026-11-17", "score": 1, "forward_return": 0.03},
        {"session_date": "2026-11-17", "score": 2, "forward_return": 0.01},
    ]
    result = rank_ic_by_date(rows)
    assert result["n_effective_dates"] == 2
    assert len(result["daily_ics"]) == 2


def test_missing_real_labels_do_not_become_classifier_accuracy():
    assert rank_ic_by_date([])["status"] == VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE
    assert brier_scores([])["status"] == VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE


def test_benchmark_basis_mismatch_is_not_alpha():
    result = benchmark_relative(
        None, "s",
        portfolio_values=[{"session_date": "d1", "value_paise": 100},
                          {"session_date": "d2", "value_paise": 99}],
        benchmark_values=[{"session_date": "d1", "value": 100,
                           "basis": "TRI", "comparability": "BASIS_MISMATCH"},
                          {"session_date": "d2", "value": 98,
                           "basis": "TRI", "comparability": "BASIS_MISMATCH"}])
    assert result["status"] == VERDICT_DATA_BLOCKED_BASIS_MISMATCH
    assert "NOT claimed" in result["note"]


def test_positive_relative_difference_can_coexist_with_absolute_loss():
    result = benchmark_relative(
        None, "s",
        portfolio_values=[{"session_date": "d1", "value_paise": 100},
                          {"session_date": "d2", "value_paise": 95}],
        benchmark_values=[{"session_date": "d1", "value": 100,
                           "basis": "PRICE_ONLY", "comparability": "COMPARABLE"},
                          {"session_date": "d2", "value": 90,
                           "basis": "PRICE_ONLY", "comparability": "COMPARABLE"}])
    assert result["portfolio_return"] < 0 < result["relative_difference"]
    assert result["verdict"] == "NOT_YET_DEMONSTRATED"


def test_missing_or_partial_marks_block_absolute_economics():
    result = absolute_economics(
        [{"session_date": "d1", "equity_paise": 100, "nav_known": False}],
        fills=[], fees=[], blocked_valuations=[{"symbol": "TCS"}],
        starting_capital_paise=100)
    assert result["status"] == VERDICT_DATA_BLOCKED
    assert result["absolute_net_return"] is None


def test_three_panels_remain_independent_and_sample_is_insufficient():
    panels = result_panels(
        scored=[], probabilities=[], nav_rows=[], fills=[], fees=[],
        blocked_valuations=[], starting_capital_paise=None,
        benchmark_rows=[], n_independent_horizons=0, minimum_horizons=60)
    assert panels["panel_A_forecast_skill"]["rank_ic"]["status"] == \
        VERDICT_GOLDSET_HOLDOUT_UNAVAILABLE
    assert panels["panel_B_absolute_economics"]["status"] == VERDICT_DATA_BLOCKED
    assert panels["sample_sufficiency"]["status"] == "INSUFFICIENT_FORWARD_SAMPLE"
    assert sample_sufficiency(3, 60)["status"] == "INSUFFICIENT_FORWARD_SAMPLE"


# ---------------------------------------------------------------------------
# worker receipts, pause/resume, missed runs and honest alerts
# ---------------------------------------------------------------------------

def worker(tmp_path, *, webhook=None, handlers=None, jobs=None):
    ledger, _ = sealed_ledger(tmp_path, stream="worker-stream")
    return ForwardWorker(
        ledger, tmp_path, "worker-stream", webhook_url=webhook,
        durable_hosting=False, handlers=handlers,
        jobs=jobs or ({"job": "signal_evaluation", "due_ist": "09:20"},
                      {"job": "execution_monitor", "due_ist": "09:21"},
                      {"job": "settlement", "due_ist": "09:22"})), ledger


def test_worker_due_jobs_are_exactly_once_with_receipts(tmp_path):
    w, ledger = worker(tmp_path)
    now = "2026-11-16T06:00:00+00:00"
    first = w.run_due(now, "2026-11-16")
    second = w.run_due(now, "2026-11-16")
    assert len(first["ran"]) == 3 and not second["ran"]
    assert len(w.receipts()) == 3
    assert len(ledger.stream_records("worker-stream", "JOB_RECEIPT")) == 3


def test_pause_blocks_new_exposure_but_keeps_exit_monitor_and_settlement(tmp_path):
    called = []
    handlers = {name: (lambda session, name=name: called.append(name) or {"ok": True})
                for name in ("signal_evaluation", "execution_monitor", "settlement")}
    w, _ = worker(tmp_path, handlers=handlers)
    w.pause("2026-11-16T03:00:00+00:00", "operator test")
    result = w.run_due("2026-11-16T06:00:00+00:00", "2026-11-16")
    assert "signal_evaluation" not in called
    assert set(called) == {"execution_monitor", "settlement"}
    assert any(row["reason"] == "NEW_EXPOSURE_PAUSED" for row in result["skipped"])
    assert w.resume("2026-11-16T06:01:00+00:00", health_ack=False)["paused"]
    assert w.resume("2026-11-16T06:02:00+00:00", health_ack=True)["paused"] is False


def test_missed_run_catchup_records_miss_without_retro_quote(tmp_path):
    w, ledger = worker(tmp_path)
    result = w.catch_up("2026-11-16T12:00:00+00:00", "2026-11-16")
    assert result["recorded"]
    assert all(row["status"] == "MISSED_CATCH_UP" for row in result["recorded"])
    assert not ledger.stream_records("worker-stream", "QUOTE_OBSERVATION")
    assert w.catch_up("2026-11-16T12:01:00+00:00", "2026-11-16")["recorded"] == []


def test_worker_holiday_and_clock_skew_fail_closed(tmp_path):
    w, _ = worker(tmp_path)
    holiday = w.run_due("2026-11-10T06:00:00+00:00", "2026-11-10")
    assert not holiday["ran"]
    w.run_due("2026-11-16T06:00:00+00:00", "2026-11-16")
    with pytest.raises(ClockSkewError):
        w.run_due("2026-11-16T05:59:59+00:00", "2026-11-16")


def test_worker_provider_failures_are_receipted_not_hidden(tmp_path):
    def unavailable(_):
        raise RuntimeError("PROVIDER_503")
    jobs = ({"job": "execution_monitor", "due_ist": "09:21"},)
    w, _ = worker(tmp_path, handlers={"execution_monitor": unavailable}, jobs=jobs)
    result = w.run_due("2026-11-16T06:00:00+00:00", "2026-11-16")
    assert result["ran"][0]["status"] == "FAILED"
    assert "PROVIDER_503" in result["ran"][0]["detail"]["error"]


def test_alerts_never_claim_delivery_without_evidence(tmp_path):
    w, _ = worker(tmp_path)
    assert w.alert_status()["status"] == "WEBHOOK_NOT_CONFIGURED"
    configured, _ = worker(tmp_path / "configured", webhook="https://example.invalid/hook")
    assert configured.alert_status()["status"] == "DRY_RUN"
    assert configured.alert_status()["delivered"] is False


def test_heartbeat_watchdog_and_health_endpoint_are_honest(tmp_path):
    w, ledger = worker(tmp_path)
    assert w.watchdog("2026-11-16T06:00:00+00:00")["status"] == "HEARTBEAT_MISSING"
    w.heartbeat("2026-11-16T06:00:00+00:00")
    assert w.watchdog("2026-11-16T06:01:00+00:00")["healthy"]
    assert w.watchdog("2026-11-16T06:03:00+00:00")["status"] == "HEARTBEAT_EXPIRED"
    health = health_endpoint(ledger, w, now_utc="2026-11-16T06:03:00+00:00")
    assert health["live_broker_surface"] is False
    assert health["readiness"]["worker_label"] == "WORKER_NOT_DURABLE"


def test_default_forward_modules_have_no_network_or_jev_mercury_imports():
    root = Path(__file__).resolve().parents[1] / "quantplus_intelligence" / "research_v3" / "forward"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "requests." not in source and "urllib.request" not in source
    assert "events_ai" not in source and "mercury_tools" not in source
    assert "place_broker_order" not in source and "live_broker_order" not in source


def test_local_health_wrapper_is_read_only_and_default_off(tmp_path):
    from scripts.wave6_worker_service import build_health_payload
    payload = build_health_payload(
        tmp_path / "missing-ledger.jsonl", now_utc="2026-11-16T06:00:00+00:00")
    assert payload["ledger"]["head_hash"] == GENESIS
    assert payload["readiness"]["worker_label"] == "WORKER_NOT_DURABLE"
    assert not (tmp_path / "missing-ledger.jsonl").exists()


def test_w5_secret_regex_ignores_report_identifiers_but_detects_credentials():
    script = Path(__file__).resolve().parents[1] / "scripts" / "wave5_verify_manifest.py"
    spec = importlib.util.spec_from_file_location("wave5_verify_manifest_for_w6", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    harmless = b"mints_new_revision ADANIPORTS_NS_1d costs_same_close"
    assert module.SECRET_PATTERN.search(harmless) is None
    assert module.SECRET_PATTERN.search(b"xpl_" + b"A" * 40) is not None
    assert module.SECRET_PATTERN.search(b"Bearer " + b"b" * 40) is not None
